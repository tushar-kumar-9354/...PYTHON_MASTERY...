import json
import pygemini
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import login
from django.db.models import Avg, Count, Max, F, Window
from django.db.models.functions import Rank
from django.core.serializers.json import DjangoJSONEncoder

from .models import (
    Course, Lesson, Quiz, Question, Option, QuizResult
)
from .forms import CourseForm


# ✅ Home page view
def home(request):
    return render(request, 'core/home.html')


# ✅ Course list view
def course_list(request):
    courses = Course.objects.all()
    return render(request, 'core/course_list.html', {'courses': courses})


# ✅ Lesson list view for a course
def lesson_list(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    lessons = course.lessons.all()
    return render(request, 'core/lesson_list.html', {'course': course, 'lessons': lessons})


# ✅ Lesson detail view
def lesson_detail(request, course_id, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id, course_id=course_id)
    return render(request, 'core/lesson_detail.html', {'lesson': lesson})


# ✅ Quiz list view for a lesson
def quiz_list(request, lesson_id):
    lesson = get_object_or_404(Lesson, pk=lesson_id)
    quizzes = lesson.quizzes.all()
    return render(request, 'core/quiz_list.html', {'lesson': lesson, 'quizzes': quizzes})


# ✅ Take a quiz
@login_required
def take_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    questions = quiz.questions.prefetch_related('options')

    if request.method == 'POST':
        score = 0
        total = questions.count()
        results = []

        for question in questions:
            selected_option_id = request.POST.get(f'question_{question.id}')
            selected_option = None
            correct_option = question.options.filter(is_correct=True).first()

            if selected_option_id:
                selected_option = Option.objects.get(pk=selected_option_id)
                if selected_option.is_correct:
                    score += 1

            results.append({
                'question': question,
                'selected_option': selected_option,
                'correct_option': correct_option
            })

        # Save quiz result
        QuizResult.objects.create(
            user=request.user,
            quiz=quiz,
            score=score,
            total_questions=total
        )

        return render(request, 'core/quiz_result.html', {
            'quiz': quiz,
            'score': score,
            'total': total,
            'results': results
        })

    return render(request, 'core/take_quiz.html', {
        'quiz': quiz,
        'questions': questions,
    })


# ✅ User Sign-up
def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('course_list')
    else:
        form = UserCreationForm()
    return render(request, 'core/signup.html', {'form': form})


# ✅ User Login
def custom_login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')
    else:
        form = AuthenticationForm()
    return render(request, 'core/login.html', {'form': form})


# ✅ My Quiz History with Analytics
@login_required
def my_quiz_history(request):
    results = QuizResult.objects.filter(user=request.user).select_related('quiz').order_by('-taken_at')

    analytics = QuizResult.objects.filter(user=request.user).aggregate(
        avg_score=Avg('score'),
        total_quizzes=Count('id')
    )

    chart_data = [
        {'quiz__title': r.quiz.title, 'score': r.score}
        for r in results
    ]

    return render(request, 'core/my_quiz_history.html', {
        'results': results,
        'analytics': analytics,
        'chart_data': json.dumps(chart_data, cls=DjangoJSONEncoder),
    })


# ✅ Leaderboard with Ranking
def leaderboard(request):
    top_scores = (
        QuizResult.objects
        .values('user__username', 'quiz__title')
        .annotate(best_score=Max('score'))
        .annotate(rank=Window(expression=Rank(), order_by=F('best_score').desc()))
        .order_by('rank')[:10]
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

            gemini_api_key = "AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"
            if not gemini_api_key:
                return JsonResponse({'error': 'Gemini API key not configured.'}, status=500)

            # Configure Gemini client
            genai.configure(api_key=gemini_api_key)

            # Initialize the model (using 'gemini-2.0-flash' for text)
            model = genai.GenerativeModel('gemini-2.0-flash')
            
            # Generate explanation
            prompt = f"""Explain this code in simple terms:
                    1. What does it do?
                    2. How does it work?
                    3. Key functions/variables

                    Code:
{code_snippet}"""
            response = model.generate_content(prompt)
            
            # Return the generated text
            explanation = response.text
            return HttpResponse(f"<pre>{explanation}</pre>")

        except Exception as e:
            print("Gemini Error:", str(e))  # Log error to console
            return JsonResponse({'error': f'AI error: {str(e)}'}, status=500)

    return HttpResponseBadRequest("Only POST requests are allowed.")
import requests
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from core.models import Lesson, Quiz, Question, Option
from django.views.decorators.csrf import csrf_exempt
import json
# === Replace with your actual Gemini API key ===
GEMINI_API_KEY = "AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"

def generate_prompt(title, content, difficulty, num_questions):
    return f"""
Generate {num_questions} multiple-choice questions for a Python tutorial.

Lesson title: {title}
Difficulty: {difficulty}
Format: Return only JSON in this format:
[
  {{
    "question": "string",
    "options": [
      {{ "text": "string", "is_correct": true/false }},
      ...
    ]
  }}
]

Lesson content:
{content}
"""


import json
import requests
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt

from core.models import Lesson, Quiz, Question, Option

# === Your Gemini API key (make sure this is set in env or settings in prod) ===
GEMINI_API_KEY = "AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
import requests
import json

from core.models import Lesson

GEMINI_API_KEY = "AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"  # Replace with your actual key

def generate_prompt(title, content, difficulty, num_questions):
    return f"""
Generate {num_questions} multiple-choice questions for a Python tutorial.

Lesson title: {title}
Difficulty: {difficulty}
Format: Return only JSON in this format:
[
  {{
    "question": "string",
    "options": [
      {{ "text": "string", "is_correct": true/false }},
      ...
    ]
  }}
]

Lesson content:
{content}
"""




### ✅ Full Code for `generate_ai_quiz` (with safe cleaning + preview)


import json
import re
import requests
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from core.models import Lesson

# Replace with your actual Gemini API key
GEMINI_API_KEY = "AIzaSyDUKAYNttTpvyilioaF9BfbPDEmw6g2ljQ"

def generate_prompt(title, content, difficulty, num_questions):
    return f"""
Generate {num_questions} multiple-choice questions for a Python tutorial.

Lesson title: {title}
Difficulty: {difficulty}
Format: Return only JSON in this format:
[
  {{
    "question": "string",
    "options": [
      {{ "text": "string", "is_correct": true/false }},
      ...
    ]
  }}
]

Lesson content:
{content}
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

        trimmed_content = lesson.content[:4000]
        prompt = generate_prompt(lesson.title, trimmed_content, difficulty, num_questions)

        try:
            response = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": GEMINI_API_KEY},
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]}
            )

            result = response.json()
            print("🔍 Gemini Full Response:", json.dumps(result, indent=2))  # Debug

            if "candidates" not in result or not result["candidates"]:
                messages.error(request, "❌ Gemini returned no content.")
                return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

            output = result["candidates"][0]["content"]["parts"][0].get("text", "").strip()
            if not output:
                raise ValueError("Gemini response was empty.")

            # ✅ Remove Markdown-style ```json block
            output_cleaned = re.sub(r"^```(?:json)?\n?", "", output)
            output_cleaned = re.sub(r"\n?```$", "", output_cleaned.strip())

            quiz_data = json.loads(output_cleaned)

            return render(request, "core/ai_quiz_preview.html", {
                "lesson": lesson,
                "quiz_data": quiz_data,
                "difficulty": difficulty,
                "num_questions": num_questions
            })

        except Exception as e:
            print("❌ Failed to parse Gemini output:", e)
            messages.error(request, "❌ AI returned invalid quiz format.")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

    return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)


from core.models import Quiz, Question, Option

@csrf_exempt
def save_ai_quiz(request, lesson_id):
    if request.method == "POST":
        lesson = get_object_or_404(Lesson, id=lesson_id)
        difficulty = request.POST.get("difficulty", "medium")
        quiz_data_json = request.POST.get("quiz_data_json", "")

        try:
            quiz_data = json.loads(quiz_data_json)
            quiz = Quiz.objects.create(
                lesson=lesson,
                title=f"{lesson.title} — AI {difficulty.capitalize()} Quiz",
                description=f"Generated with AI"
            )

            for q in quiz_data:
                question = Question.objects.create(quiz=quiz, question_text=q["question"])
                for opt in q["options"]:
                    Option.objects.create(
                        question=question,
                        option_text=opt["text"],
                        is_correct=opt["is_correct"]
                    )

            messages.success(request, "✅ Quiz saved successfully.")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

        except Exception as e:
            print("❌ Failed to save quiz:", e)
            messages.error(request, "❌ Failed to save quiz.")
            return redirect("lesson_detail", course_id=lesson.course.id, lesson_id=lesson.id)

    return redirect("course_list")
