from django import template

register = template.Library()

@register.filter
def get_question_answer(answers, question):
    for answer in answers:
        if answer.question == question:
            return answer
    return None
