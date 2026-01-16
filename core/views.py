import json
import re
import os
import time
from django.core.cache import cache
from dotenv import load_dotenv
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login
from django.contrib import messages
from django.db.models import Avg, Count, Max, F, Window
from django.db.models.functions import Rank
from django.core.serializers.json import DjangoJSONEncoder
from django.views.decorators.csrf import csrf_exempt

import google.generativeai as genai

from .models import (
    Course, Lesson, Quiz, Question, Option, QuizResult, UserAnswer, QuizAttempt, Answer
)
from .forms import CourseForm

# Load env variables
load_dotenv(override=True)

# USE A SINGLE API KEY CONSISTENTLY
GEMINI_API_KEY = "AIzaSyA_NReqnryUk7hpyouKS23j7TOTOI8nSqE"  # Your working key
GEMINI_API_KEY_FOR_QUIZ = 'AIzaSyCEvGKK8NoNRmKWcfz-sRVtj0g1Kd2qmhY'

# Token usage tracking dictionary
token_usage = {
    'total_tokens_used': 0,
    'total_requests': 0,
    'last_request_time': None,
    'requests_by_endpoint': {}
}

def update_token_usage(endpoint, input_tokens, output_tokens, total_tokens):
    """Update token usage statistics"""
    global token_usage
    
    token_usage['total_tokens_used'] += total_tokens
    token_usage['total_requests'] += 1
    token_usage['last_request_time'] = time.time()
    
    if endpoint not in token_usage['requests_by_endpoint']:
        token_usage['requests_by_endpoint'][endpoint] = {
            'count': 0,
            'total_tokens': 0,
            'input_tokens': 0,
            'output_tokens': 0
        }
    
    token_usage['requests_by_endpoint'][endpoint]['count'] += 1
    token_usage['requests_by_endpoint'][endpoint]['total_tokens'] += total_tokens
    token_usage['requests_by_endpoint'][endpoint]['input_tokens'] += input_tokens
    token_usage['requests_by_endpoint'][endpoint]['output_tokens'] += output_tokens
    
    # Log token usage
    print(f"\n📊 TOKEN USAGE - {endpoint}:")
    print(f"   Input tokens: {input_tokens}")
    print(f"   Output tokens: {output_tokens}")
    print(f"   Total tokens: {total_tokens}")
    print(f"   Cumulative total: {token_usage['total_tokens_used']} tokens")
    print(f"   Total requests: {token_usage['total_requests']}")
    
    return total_tokens

def get_token_usage_stats():
    """Get current token usage statistics"""
    global token_usage
    return {
        'total_tokens_used': token_usage['total_tokens_used'],
        'total_requests': token_usage['total_requests'],
        'last_request_time': token_usage['last_request_time'],
        'requests_by_endpoint': token_usage['requests_by_endpoint'],
        'estimated_cost': token_usage['total_tokens_used'] * 0.00000025,  # Rough estimate: $0.00000025 per token
        'tokens_remaining': 1000000 - token_usage['total_tokens_used'] if token_usage['total_tokens_used'] < 1000000 else 0
    }

def count_tokens_for_text(text):
    """Approximate token count for text (rough estimation)"""
    # Rough estimation: 1 token ≈ 4 characters for English text
    # For more accurate count, we'd need to use the API's countTokens method
    return len(text) // 4

# ✅ Home page
def home(request):
    return render(request, 'core/home.html')

# ✅ Course list
def course_list(request):
    courses = Course.objects.all()
    return render(request, 'core/course_list.html', {'courses': courses})

# ✅ Lesson list for a course
def lesson_list(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    search_query = request.GET.get('q', '').strip()  # Get search term if any

    if search_query:
        lessons = course.lessons.filter(title__icontains=search_query)
    else:
        lessons = course.lessons.all()

    context = {
        'course': course,
        'lessons': lessons,
        'search_query': search_query,
    }
    return render(request, 'core/lesson_list.html', context)

# ✅ Lesson detail view
def lesson_detail(request, course_id, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id, course_id=course_id)
    return render(request, 'core/lesson_detail.html', {'lesson': lesson})

# ✅ Quiz list for a lesson (shows user's selected answers if available)
def quiz_list(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    questions = Question.objects.filter(quiz__lesson=lesson)
    quizzes = []

    for question in questions:
        try:
            user_answer = UserAnswer.objects.get(user=request.user, question=question)
            selected_option = user_answer.selected_option
        except UserAnswer.DoesNotExist:
            selected_option = None

        quizzes.append({'question': question, 'selected_option': selected_option})

    return render(request, 'core/quiz_list.html', {'lesson': lesson, 'quizzes': quizzes})

# ✅ Take a quiz (POST handles submission)
@login_required
def take_quiz(request, lesson_id, quiz_id):
    quiz = get_object_or_404(Quiz, id=quiz_id, lesson_id=lesson_id)
    questions = quiz.questions.prefetch_related('options').all()

    if request.method == 'POST':
        score = 0
        total = questions.count()
        results = []

        # Create initial attempt
        attempt = QuizResult.objects.create(
            user=request.user,
            quiz=quiz,
            score=0,
            total_questions=total
        )

        for question in questions:
            selected_option_id = request.POST.get(f'question_{question.id}')
            selected_option = None
            correct_option = question.options.filter(is_correct=True).first()
            is_correct = False

            if selected_option_id:
                try:
                    selected_option = Option.objects.get(pk=selected_option_id)
                    is_correct = selected_option.is_correct
                except Option.DoesNotExist:
                    pass

                # Save answer
                Answer.objects.create(
                    attempt=attempt,
                    question=question,
                    selected_option=selected_option,
                    is_correct=is_correct
                )

                # Save/update user's latest answer
                UserAnswer.objects.update_or_create(
                    user=request.user,
                    question=question,
                    defaults={'selected_option': selected_option, 'is_correct': is_correct}
                )

                if is_correct:
                    score += 1

            results.append({
                'question': question,
                'selected_option': selected_option,
                'correct_option': correct_option
            })

        attempt.score = score
        attempt.save()

        # Update or create quiz result
        QuizResult.objects.update_or_create(
            user=request.user,
            quiz=quiz,
            defaults={'score': score, 'total_questions': total}
        )

        return render(request, 'core/quiz_result.html', {
            'quiz': quiz,
            'score': score,
            'total': total,
            'results': results
        })

    # GET request
    return render(request, 'core/take_quiz.html', {
        'quiz': quiz,
        'questions': questions
    })

# ✅ Signup
def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'core/signup.html', {'form': form})

# ✅ Login
def custom_login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('home')
    else:
        form = AuthenticationForm()
    return render(request, 'core/login.html', {'form': form})

# ✅ My quiz history with analytics
@login_required
def my_quiz_history(request):
    results = QuizResult.objects.filter(user=request.user)\
                .select_related('lesson')\
                .order_by('-submitted_at')

    analytics = QuizResult.objects.filter(user=request.user).aggregate(
        avg_score=Avg('score'),
        total_quizzes=Count('id')
    )

    chart_data = [
        {'quiz__title': r.lesson.title, 'score': r.score}
        for r in results
    ]

    # ✅ Create a JSON-serializable version of results
    results_as_dict = [
        {
            'lesson': {'title': r.lesson.title},
            'score': r.score,
            'total': r.total,
            'submitted_at': r.submitted_at.isoformat()
        }
        for r in results
    ]

    return render(request, 'core/my_quiz_history.html', {
        'results': results,
        'analytics': analytics,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),
        'results_json': json.dumps(results_as_dict, cls=DjangoJSONEncoder),  # ✅ Needed for CSV
    })

# ✅ Leaderboard with ranking
def leaderboard(request):
    top_scores = (
        QuizResult.objects
        .values('user__username', 'lesson__title')  
        .annotate(best_score=Max('score'))
        .annotate(rank=Window(expression=Rank(), order_by=F('best_score').desc()))
        .order_by('-best_score')[:20]
        
    )

    user_rank = None
    if request.user.is_authenticated:
        all_scores = (
            QuizResult.objects
            .values('user__username')
            .annotate(best_score=Max('score'))
            .annotate(rank=Window(expression=Rank(), order_by=F('best_score').desc()))
        )
        for row in all_scores:
            if row['user__username'] == request.user.username:
                user_rank = row['rank']
                break

    return render(request, 'core/leaderboard.html', {
        'top_scores': top_scores,
        'user_rank': user_rank
    })

# ✅ Admin-only course creation
@staff_member_required
def create_course(request):
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('course_list')
    else:
        form = CourseForm()
    return render(request, 'core/create_course.html', {'form': form})

# ✅ Gemini AI assistant for code explanations - WITH TOKEN TRACKING
def get_gemini_explanation(request):
    if request.method == 'POST':
        try:
            code_snippet = request.POST.get('code_snippet', '').strip()
            if not code_snippet:
                return HttpResponse("Please provide text to explain.")

            if not GEMINI_API_KEY_FOR_QUIZ:
                return JsonResponse({'error': 'Gemini API key not configured.'}, status=500)

            # Configure with the single API key
            genai.configure(api_key=GEMINI_API_KEY_FOR_QUIZ)
            model = genai.GenerativeModel('gemma-3-1b-it')
            
            prompt = f"Explain this Python code simply for a beginner. Use bullet points. Code: {code_snippet}"
            
            # Estimate input tokens
            input_tokens = count_tokens_for_text(prompt)
            print(f"📝 Explanation request - Input tokens (estimated): {input_tokens}")
            
            response = model.generate_content(prompt)
            explanation = response.text
            
            # Estimate output tokens
            output_tokens = count_tokens_for_text(explanation)
            total_tokens = input_tokens + output_tokens
            
            # Update token usage
            update_token_usage('get_gemini_explanation', input_tokens, output_tokens, total_tokens)
            
            # Add token info to response
            token_info = f"\n\n🔹 Token Usage: {input_tokens} input + {output_tokens} output = {total_tokens} total tokens"
            explanation_with_tokens = explanation + token_info
            
            return HttpResponse(f"<pre>{explanation_with_tokens}</pre>")

        except Exception as e:
            print("Gemini Error:", str(e))
            return JsonResponse({'error': f'AI error: {str(e)}'}, status=500)

    return HttpResponseBadRequest("Only POST requests are allowed.")

def generate_prompt(title, content, difficulty, num_questions):
    return f"""
Generate {num_questions} MCQs for "{title}". 
Difficulty: {difficulty}.
Content: {content}

Output ONLY valid JSON:
[
  {{
    "question": "Question text?",
    "options": ["Choice0", "Choice1", "Choice2", "Choice3"],
    "correct_index": 0
  }}
]
Rules:
- correct_index MUST be 0, 1, 2, or 3.
- No markdown formatting.
- Ensure questions are directly related to the content.
"""

@csrf_exempt
@login_required
def generate_ai_quiz(request, lesson_id):
    # Add rate limiting to prevent quota errors
    user_id = request.user.id if request.user.is_authenticated else request.META.get('REMOTE_ADDR')
    cache_key = f"quiz_gen_{user_id}"
    
    # Limit to 1 request per 30 seconds per user
    if cache.get(cache_key):
        messages.error(request, "Please wait 30 seconds before generating another quiz.")
        return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)
    
    lesson = get_object_or_404(Lesson, id=lesson_id)

    if request.method == "POST":
        difficulty = request.POST.get("difficulty", "medium")
        try:
            num_questions = int(request.POST.get("num_questions", 1))
        except ValueError:
            num_questions = 1

        prompt = generate_prompt(lesson.title, lesson.content[:3000], difficulty, num_questions)
        
        # Estimate input tokens before API call
        input_tokens = count_tokens_for_text(prompt)
        print(f"📝 Quiz generation - Input tokens (estimated): {input_tokens}")
        print(f"📝 Prompt length: {len(prompt)} characters")
        print(f"📝 Lesson content used: {len(lesson.content[:3000])} characters")

        try:
            # Use the single API key
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel('gemma-3-1b-it')
            
            # Add retry logic for rate limits
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    response = model.generate_content(prompt)
                    text = response.text.strip()
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < max_retries - 1:
                        time.sleep(2)  # Wait 2 seconds before retry
                        continue
                    else:
                        raise
            
            # Estimate output tokens
            output_tokens = count_tokens_for_text(text)
            total_tokens = input_tokens + output_tokens
            
            # Update token usage
            update_token_usage('generate_ai_quiz', input_tokens, output_tokens, total_tokens)
            
            print(f"📝 AI Response length: {len(text)} characters")
            print(f"📝 Output tokens (estimated): {output_tokens}")
            
            # 1. Clean Markdown and extract JSON
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            
            quiz_data = json.loads(text)

            # 2. FIX: Convert single object to list if necessary (Prevents 'slice' error)
            if isinstance(quiz_data, dict):
                quiz_data = [quiz_data]
            
            # 3. Slice to the requested number of questions
            quiz_data = quiz_data[:num_questions]

            # 4. Final Validation for correct_index and options
            for q in quiz_data:
                # Ensure index is within 0-3
                if q.get('correct_index', 0) > 3:
                    q['correct_index'] = 0 
                # Ensure exactly 4 options exist
                while len(q.get('options', [])) < 4:
                    q['options'].append("N/A")

            quiz_json = json.dumps(quiz_data)
            
            # Set cache for rate limiting
            cache.set(cache_key, True, 30)
            
            # Add token info to context
            token_info = {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': total_tokens,
                'cumulative_total': token_usage['total_tokens_used']
            }

            return render(request, "core/ai_quiz_preview.html", {
                "lesson": lesson,
                "quiz_data": quiz_data,
                "quiz_json": quiz_json,
                "difficulty": difficulty,
                "num_questions": num_questions,
                "token_info": token_info
            })

        except json.JSONDecodeError as e:
            messages.error(request, f"Failed to parse AI response. Please try again. Error: {str(e)}")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)
        except Exception as e:
            print(f"DEBUG ERROR: {str(e)}")
            messages.error(request, f"AI Error: {str(e)}")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

    return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

@login_required
def save_ai_quiz(request, lesson_id):
    if request.method == "POST":
        lesson = get_object_or_404(Lesson, id=lesson_id)
        quiz_data_json = request.POST.get('quiz_data_json')
        difficulty = request.POST.get('difficulty')

        try:
            quiz_data = json.loads(quiz_data_json)
        except json.JSONDecodeError:
            return render(request, "core/error.html", {"message": "Invalid quiz data."})

        score = 0
        total = len(quiz_data)
        results = []

        for i, q in enumerate(quiz_data):
            selected_index = request.POST.get(f"q{i}")
            correct_index = q.get("correct_index", 0)

            is_correct = False
            if selected_index is not None:
                try:
                    is_correct = int(selected_index) == correct_index
                except (ValueError, TypeError):
                    is_correct = False
                    
            if is_correct:
                score += 1

            results.append({
                "question": q.get("question"),
                "selected": q["options"][int(selected_index)] if selected_index is not None and selected_index.isdigit() and 0 <= int(selected_index) < len(q.get('options', [])) else None,
                "correct": q["options"][correct_index] if correct_index < len(q.get('options', [])) else "N/A",
                "is_correct": is_correct
            })

        # Save QuizResult
        QuizResult.objects.create(
            user=request.user,
            lesson=lesson,
            difficulty=difficulty,
            score=score,
            total=total,
        )

        return render(request, "core/quiz_result.html", {
            "score": score,
            "total": total,
            "results": results,
            "lesson": lesson,
            "difficulty": difficulty
        })
    else:
        return redirect("home")

@login_required
def quiz_result(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, user=request.user)
    answers = Answer.objects.filter(attempt=attempt)
    return render(request, 'lessons/quiz_result.html', {
        'attempt': attempt,
        'answers': answers
    })

# Test API key view for debugging - WITH TOKEN TRACKING
def test_api_key(request):
    try:
        # Test with the configured API key
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemma-3-1b-it')
        
        test_prompt = "Say 'Hello World' and tell me about Python programming in one sentence."
        input_tokens = count_tokens_for_text(test_prompt)
        print(f"📝 Test API - Input tokens (estimated): {input_tokens}")
        
        response = model.generate_content(test_prompt)
        
        output_tokens = count_tokens_for_text(response.text)
        total_tokens = input_tokens + output_tokens
        
        # Update token usage
        update_token_usage('test_api_key', input_tokens, output_tokens, total_tokens)
        
        # Get current stats
        stats = get_token_usage_stats()
        
        return HttpResponse(f"""
        <h3>✅ Success! API Key is working.</h3>
        <p><strong>Response:</strong> {response.text}</p>
        <hr>
        <h4>📊 Token Usage for this request:</h4>
        <p>Input tokens: {input_tokens}</p>
        <p>Output tokens: {output_tokens}</p>
        <p>Total tokens: {total_tokens}</p>
        <hr>
        <h4>📈 Cumulative Usage:</h4>
        <p>Total tokens used: {stats['total_tokens_used']}</p>
        <p>Total requests: {stats['total_requests']}</p>
        <p>Estimated remaining tokens: {stats['tokens_remaining']}</p>
        <p>Estimated cost: ${stats['estimated_cost']:.6f}</p>
        <hr>
        <p><small>Using key: {GEMINI_API_KEY[:20]}...</small></p>
        """)
    except Exception as e:
        return HttpResponse(f"<h3>❌ Error!</h3><p>{str(e)}</p><p>Using key: {GEMINI_API_KEY[:20]}...</p>")

def test_api_key_1(request):
    try:
        # Test with the configured API key
        genai.configure(api_key=GEMINI_API_KEY_FOR_QUIZ)
        model = genai.GenerativeModel('gemma-3-1b-it')
        
        test_prompt = "Say 'Hello World' from the second API key."
        input_tokens = count_tokens_for_text(test_prompt)
        print(f"📝 Test API 2 - Input tokens (estimated): {input_tokens}")
        
        response = model.generate_content(test_prompt)
        
        output_tokens = count_tokens_for_text(response.text)
        total_tokens = input_tokens + output_tokens
        
        # Update token usage
        update_token_usage('test_api_key_1', input_tokens, output_tokens, total_tokens)
        
        return HttpResponse(f"""
        <h3>✅ Success! Second API Key is working.</h3>
        <p><strong>Response:</strong> {response.text}</p>
        <hr>
        <h4>📊 Token Usage:</h4>
        <p>Input tokens: {input_tokens}</p>
        <p>Output tokens: {output_tokens}</p>
        <p>Total tokens: {total_tokens}</p>
        <hr>
        <p><small>Using key: {GEMINI_API_KEY_FOR_QUIZ[:20]}...</small></p>
        """)
    except Exception as e:
        return HttpResponse(f"<h3>❌ Error!</h3><p>{str(e)}</p><p>Using key: {GEMINI_API_KEY_FOR_QUIZ[:20]}...</p>")

# Add a new view to display token usage dashboard
@login_required
def token_usage_dashboard(request):
    """Display token usage statistics"""
    stats = get_token_usage_stats()
    
    # Format for display
    formatted_stats = {
        'total_tokens_used': f"{stats['total_tokens_used']:,}",
        'total_requests': stats['total_requests'],
        'estimated_cost': f"${stats['estimated_cost']:.6f}",
        'tokens_remaining': f"{stats['tokens_remaining']:,}" if stats['tokens_remaining'] > 0 else "Unlimited",
        'last_request_time': time.ctime(stats['last_request_time']) if stats['last_request_time'] else 'Never',
    }
    
    # Prepare endpoint breakdown
    endpoint_breakdown = []
    for endpoint, data in stats['requests_by_endpoint'].items():
        endpoint_breakdown.append({
            'endpoint': endpoint,
            'count': data['count'],
            'total_tokens': f"{data['total_tokens']:,}",
            'avg_per_request': f"{data['total_tokens'] // data['count']:,}" if data['count'] > 0 else "0"
        })
    
    return render(request, 'core/token_dashboard.html', {
        'stats': formatted_stats,
        'endpoint_breakdown': endpoint_breakdown,
        'api_keys_info': {
            'gemini_key': GEMINI_API_KEY[:15] + '...' if GEMINI_API_KEY else 'Not set',
            'gemini_quiz_key': GEMINI_API_KEY_FOR_QUIZ[:15] + '...' if GEMINI_API_KEY_FOR_QUIZ else 'Not set'
        }
    })

# Add a simple fallback function for when API is unavailable
def get_fallback_explanation(code_snippet):
    """Provide basic explanations when Gemini API is unavailable"""
    return "The AI explanation service is currently unavailable. Here are some general tips for understanding Python code:\n\n1. Read the code line by line\n2. Look for variable names and their purposes\n3. Identify loops and conditional statements\n4. Check function definitions and calls\n5. Trace the flow of data through the code"

# Add this to reset token counts (admin only)
@staff_member_required
def reset_token_counts(request):
    """Reset token usage counts (admin only)"""
    global token_usage
    token_usage = {
        'total_tokens_used': 0,
        'total_requests': 0,
        'last_request_time': None,
        'requests_by_endpoint': {}
    }
    messages.success(request, "Token usage statistics have been reset.")
    return redirect('token_usage_dashboard')