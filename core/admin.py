from django.contrib import admin
from .models import Course, Lesson, Quiz, Question, Option, QuizResult

class OptionInline(admin.TabularInline):
    model = Option
    extra = 4

class QuestionAdmin(admin.ModelAdmin):
    inlines = [OptionInline]

class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'lesson')

class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'course')
    list_filter = ('course',)

class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'description')

admin.site.register(Course, CourseAdmin)
admin.site.register(Lesson, LessonAdmin)
admin.site.register(Quiz, QuizAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(QuizResult)
