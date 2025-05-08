from django.contrib import admin
from django.urls import path, include  # include lets us modularize

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),  # 👈 all homepage routes in 'core'
    path('accounts/', include('django.contrib.auth.urls')),  # 👈 Add this
    path('ckeditor/', include('ckeditor_uploader.urls')),

]
from django.conf import settings
from django.conf.urls.static import static
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

