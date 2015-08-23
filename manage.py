from django.conf.urls import patterns

import app_manage

urlpatterns = patterns('')

if __name__ == '__main__':
    app_manage.main(
        [],
        DATABASES=app_manage.DatabaseConfig(
            default='sqlite://localhost/:memory:'
        ),
        ROOT_URLCONF='manage',
    )
