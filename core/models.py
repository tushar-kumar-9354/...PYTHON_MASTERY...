from django.db import models
from django.contrib.auth.models import User

# Model for Courses
class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


# Model for Lessons
from django.db import models
content = models.TextField()  # Use TextField for plain text content

class Lesson(models.Model):
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=200)
    content = models.TextField()  # Use TextField for plain text content
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.title}"


# Model for Quizzes
class Quiz(models.Model):
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='quizzes',
        default=1  # Assumes there is a Lesson with ID=1
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='quizzes')

    def __str__(self):
        return self.title


# Model for Quiz Questions
class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.CharField(max_length=500)

    def __str__(self):
        return self.question_text


# Model for Quiz Options
class Option(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=200)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.option_text


# Model for Quiz Results
class QuizResult(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_results')
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    score = models.IntegerField()
    total_questions = models.IntegerField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    taken_at = models.DateTimeField(auto_now_add=True)  # or use auto_now=True if you want it updated every time

    def __str__(self):
        return f'{self.user.username} - {self.quiz.title} ({self.score}/{self.total_questions})'
