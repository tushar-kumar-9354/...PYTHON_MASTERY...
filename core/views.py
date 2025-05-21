import json
import os
import re
import pygemini
import requests
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
    Course, Lesson, Quiz, Question, Option, QuizResult, UserAnswer ,QuizAttempt, Answer
)
from .forms import CourseForm

# Load env variables
load_dotenv()
GEMINI_API_KEY ="AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"


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
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Quiz, Option, Answer, QuizResult, UserAnswer
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
from django.db.models import F, Max, Window
from django.db.models.functions import Rank

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


# ✅ Gemini AI assistant
from django.http import JsonResponse, HttpResponseBadRequest
import os
import pygemini
import json

import pygemini


import os
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
import google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()  # Before accessing os.getenv()
def get_gemini_explanation(request):
    if request.method == 'POST':
        try:
            code_snippet = request.POST.get('code_snippet')
            if not code_snippet:
                return JsonResponse({'error': 'No code provided.'}, status=400)

            gemini_api_key = "own api key"
            if not gemini_api_key:
                return JsonResponse({'error': 'Gemini API key not configured.'}, status=500)

            # Configure Gemini client
            genai.configure(api_key=gemini_api_key)

            # Initialize the model (using 'gemini-2.0-flash' for text)
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # Generate explanation
            prompt = f"""
                    You are an AI Python Language Assistant integrated into an online course platform.

                    When a user types something like:
                    - "Summarize the above lesson"
                    - "Explain the above code"
                    - "Give a simple explanation of this chapter"

                    ...you should:
                    1. Automatically refer to the **Python lesson content that appears just above the chat box** (assume you have access to it).
                    2. Provide a **clear, beginner-friendly summary** of that content.
                    3. Include:
                    - ✅ What is this.
                    - ✅ What the function or concept does.
                    - ✅ How it works (step-by-step if needed).
                    - ✅ Key functions/keywords used.
                    4. If code is included:
                    - 🧠 Break it down step-by-step.
                    - 📌 Use headings, bullet points, and code blocks for clarity.

                    Your goal is to make the lesson easy to understand like a Python tutor would.



{code_snippet}"""
            response = model.generate_content(prompt)
            
            # Return the generated text
            explanation = response.text
            return HttpResponse(f"<pre>{explanation}</pre>")

        except Exception as e:
            print("Gemini Error:", str(e))  # Log error to console
            return JsonResponse({'error': f'AI error: {str(e)}'}, status=500)

    return HttpResponseBadRequest("Only POST requests are allowed.")


# Pull this from settings or env in production


import json
import re
import requests
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from .models import Lesson, Quiz, Question, Option


GEMINI_API_KEY = "AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"  # make sure this is set in your settings

def generate_prompt(title, content, difficulty, num_questions):
    return f"""
You are an expert educational AI quiz generator.

Generate exactly {num_questions} multiple-choice questions for the lesson titled "{title}".

Lesson content:
{content}

Instructions:
- Difficulty: {difficulty} (easy/medium/hard)
- Each question must have exactly 4 options.
- Only one option is correct.
- Return **only** valid JSON in this format:

[
  {{
    "question": "Question text?",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "correct_index": 2
  }}
]

Do not wrap the JSON in markdown or code fences.
"""

@csrf_exempt
def generate_ai_quiz(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)

    if request.method == "POST":
        difficulty = request.POST.get("difficulty", "medium")
        try:
            num_questions = int(request.POST.get("num_questions", 3))
        except ValueError:
            num_questions = 3

        # Trim content to avoid hitting API-size limits
        trimmed_content = lesson.content[:3000]
        prompt = generate_prompt(lesson.title, trimmed_content, difficulty, num_questions)

        # Call Gemini 2.0 Flash
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            params={"key": GEMINI_API_KEY},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        result = r.json()

        if "candidates" not in result or not result["candidates"]:
            messages.error(request, "AI returned no quiz data.")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

        text = result["candidates"][0]["content"]["parts"][0].get("text", "").strip()
        # Remove any accidental fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            quiz_data = json.loads(text)
        except Exception:
            messages.error(request, "Failed to parse AI output.")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)


# … inside generate_ai_quiz after quiz_data = json.loads(text) …

        quiz_json = json.dumps(quiz_data)

        return render(request, "core/ai_quiz_preview.html", {
            "lesson": lesson,
            "quiz_data": quiz_data,       # for rendering questions
            "quiz_json": quiz_json,       # the valid JSON string
            "difficulty": difficulty,
            "num_questions": num_questions
        })


    # Dump back to JSON with proper double quotes
   
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from core.models import Lesson, QuizResult
import json

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
            correct_index = q.get("correct_index")

            is_correct = str(selected_index) == str(correct_index)
            if is_correct:
                score += 1

            results.append({
                "question": q.get("question"),
                "selected": q["options"][int(selected_index)] if selected_index is not None else None,
                "correct": q["options"][correct_index],
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
        return redirect("dashboard")  # or your fallback page
 

    if request.method == "POST":
        lesson = get_object_or_404(Lesson, id=lesson_id)
        difficulty = request.POST.get("difficulty", "medium")

        try:
            quiz_data = json.loads(request.POST.get("quiz_data_json", "[]"))
        except json.JSONDecodeError:
            messages.error(request, "Invalid quiz data.")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

        # Create the Quiz
        quiz = Quiz.objects.create(
            lesson=lesson,
            title=f"{lesson.title} — AI {difficulty.capitalize()} Quiz",
            description="Auto-generated quiz"
        )

        # Create Questions & Options, supplying a non-null explanation
        for item in quiz_data:
            q = Question.objects.create(
                quiz=quiz,
                question_text=item["question"],
                explanation=""                  # ← this fixes the NOT NULL error
            )
            for idx, opt_text in enumerate(item["options"]):
                Option.objects.create(
                    question=q,
                    option_text=opt_text,
                    is_correct=(idx == item["correct_index"])
                )

        messages.success(request, "Quiz saved to database!")
        return redirect("quiz_list", lesson_id=lesson.id)

    return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)
@login_required
def quiz_result(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, id=attempt_id, user=request.user)
    answers = Answer.objects.filter(attempt=attempt)
    return render(request, 'lessons/quiz_result.html', {
        'attempt': attempt,
        'answers': answers
    })
