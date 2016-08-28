try:
    from django.conf.urls import patterns
except ImportError:
    patterns = lambda x: []

import app_manage

urlpatterns = patterns('')

if __name__ == '__main__':
    app_manage.main(
        ['better_test'],
        DATABASES=app_manage.DatabaseConfig(
            default='sqlite://localhost/:memory:'
        ),
        ROOT_URLCONF='manage',
    )

