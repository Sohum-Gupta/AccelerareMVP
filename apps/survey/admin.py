from django.contrib import admin

from .models import Question, SurveyVersion

# Questions are changed through services.load_questions (the private file), so
# the admin only shows them.


class ReadOnlyQuestions(admin.TabularInline):
    model = Question
    extra = 0
    can_delete = False
    fields = ("position", "text", "min_value", "max_value", "metadata")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SurveyVersion)
class SurveyVersionAdmin(admin.ModelAdmin):
    list_display = ("number", "published_at", "question_count")
    inlines = [ReadOnlyQuestions]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("survey_version", "position", "text")
    list_filter = ("survey_version",)
    readonly_fields = ("survey_version", "position", "text", "min_value", "max_value", "metadata")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
