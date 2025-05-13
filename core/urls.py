from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('courses/', views.course_list, name='course_list'),
    path('courses/<int:course_id>/lessons/', views.lesson_list, name='lesson_list'),
    path('lessons/<int:lesson_id>/quizzes/', views.quiz_list, name='quiz_list'),
    path('quiz/<int:quiz_id>/take/', views.take_quiz, name='take_quiz'),
    path('signup/', views.signup_view, name='signup'),
    path('accounts/login/', views.custom_login_view, name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('my-quiz-history/', views.my_quiz_history, name='my_quiz_history'),
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('courses/<int:course_id>/lessons/<int:lesson_id>/', views.lesson_detail, name='lesson_detail'),
    # core/urls.py
    path('ai/explain/', views.get_gemini_explanation, name='ai_explain'),
    path('lesson/<int:lesson_id>/generate_quiz/', views.generate_ai_quiz, name='generate_ai_quiz'),
    path('lesson/<int:lesson_id>/save_ai_quiz/', views.save_ai_quiz, name='save_ai_quiz'),
    path('lessons/<int:lesson_id>/quizzes/<int:quiz_id>/', views.take_quiz, name='take_quiz'),
    path('quizzes/result/<int:attempt_id>/', views.quiz_result, name='quiz_result'),
    
   
]
