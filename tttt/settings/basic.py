# Django settings for tttt project.

import os
from django.conf import global_settings

ROOT_PATH = os.path.abspath("%s/%s/" % (os.path.dirname(os.path.realpath(__file__)), "../.."))

DEBUG = True
TEMPLATE_DEBUG = DEBUG

VERSION = "1.0beta"

ADMINS = (
    # ('Example', 'admin@example.com'),
)

MANAGERS = ADMINS

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3', # Add 'postgresql_psycopg2', 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
        'NAME': ROOT_PATH + '/data.db',                      # Or path to database file if using sqlite3.
        'USER': '',                      # Not used with sqlite3.
        'PASSWORD': '',                  # Not used with sqlite3.
        'HOST': '',                      # Set to empty string for localhost. Not used with sqlite3.
        'PORT': '',                      # Set to empty string for default. Not used with sqlite3.
    }
}

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/1.4/ref/settings/#allowed-hosts
ALLOWED_HOSTS = []

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# In a Windows environment this must be set to your system time zone.
TIME_ZONE = 'Europe/Prague'

DATETIME_FORMAT = 'Y-m-d H:i'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# If you set this to False, Django will not format dates, numbers and
# calendars according to the current locale.
USE_L10N = False

# If you set this to False, Django will not use timezone-aware datetimes.
USE_TZ = True

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/home/media/media.lawrence.com/media/"
MEDIA_ROOT = (
    "%s/%s/" % (ROOT_PATH, 'tttt/media')
)

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://media.lawrence.com/media/", "http://example.com/media/"
MEDIA_URL = '/media/'

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/home/media/media.lawrence.com/static/"
STATIC_ROOT = "%s/tttt/%s/" % (ROOT_PATH, 'static')

# URL prefix for static files.
# Example: "http://media.lawrence.com/static/"
STATIC_URL = '/static/'

# URL to gitweb
GITWEB_URL = '/gitweb/'

# Additional locations of static files
STATICFILES_DIRS = (
    # Put strings here, like "/home/html/static" or "C:/www/django/static".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
)

# List of finder classes that know how to find static files in
# various locations.
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
#    'django.contrib.staticfiles.finders.DefaultStorageFinder',
)

# Make this unique, and don't share it with anybody.
SECRET_KEY = ''

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
    # 'django.template.loaders.eggs.Loader',
)

MIDDLEWARE_CLASSES = (
    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # Uncomment the next line for simple clickjacking protection:
    # 'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

TEMPLATE_CONTEXT_PROCESSORS = global_settings.TEMPLATE_CONTEXT_PROCESSORS + (
    "django.contrib.auth.context_processors.auth",
    "django.core.context_processors.request",
    "tttt.context_processors.basic",
)

TASKOMATIC_HOOKS = (
    'apps.core.management.commands',
)

ROOT_URLCONF = 'tttt.urls'

# Python dotted path to the WSGI application used by Django's runserver.
WSGI_APPLICATION = 'tttt.wsgi.application'

TEMPLATE_DIRS = (
    # Put strings here, like "/home/html/django_templates" or "C:/www/django/templates".
    # Always use forward slashes, even on Windows.
    # Don't forget to use absolute paths, not relative paths.
    "%s/%s/" % (ROOT_PATH, 'tttt/templates'),
)

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'grappelli.dashboard',
    'grappelli',
    'django.contrib.admin',
    'django.contrib.admindocs',
    'widget_tweaks',
    'debug_toolbar',
    'apps.core',
    'apps.waiver',
    'apps.taskomatic',
    'apps.kerberos',
    'apps.api',
    'django_extensions',
    'south',
    'taggit',
    'reversion',
    'rest_framework',
)

SOUTH_MIGRATION_MODULES = {
    'taggit': 'taggit.south_migrations',
}

# A sample logging configuration. The only tangible logging
# performed by this configuration is to send an email to
# the site admins on every HTTP 500 error when DEBUG=False.
# See http://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
    'formatters': {
        'verbose': {
            'format': '%(asctime)s %(levelname)s %(module)s.%(funcName)s'
                      '(line no. %(lineno)d): %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
        'simple': {
            'format': '%(levelname)s %(module)s.%(funcName)s(%(lineno)d): '
                      '%(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse'
        }
    },
    'handlers': {
       'mail_admins': {
            'level': 'ERROR',
            'filters': ['require_debug_false'],
            'class': 'django.utils.log.AdminEmailHandler',
            'include_html': True,
        },
        'console': {
            'level': 'INFO',  # 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': True,
        },
    },
    'root': {
        'handlers': ['mail_admins'],
        'level': 'INFO'
    },
}

KRB5_TEST_USER = "username"
KRB5_TEST_PASSWORD = "password"

# kerberos realm and service
KRB5_REALM = 'EXAMPLE.COM'
KRB5_SERVICE = 'krbtgt@AS.EXAMPLE.COM'

# redirect url after login
LOGIN_REDIRECT_URL = '/'

if int(os.environ.get("DDD", 0)) > 0:
    #LOGGING['loggers']['commands']['handlers'] = ['console', ]
    #LOGGING['loggers']['commands']['propagate'] = False
    LOGGING['root']['handlers'].append('console')

    # Enabling django-debug-toolbar..."
    MIDDLEWARE_CLASSES = ('debug_toolbar.middleware.DebugToolbarMiddleware',) \
                            + MIDDLEWARE_CLASSES

    DEBUG_TOOLBAR_CONFIG = {
       'INTERCEPT_REDIRECTS': False,
    }


# beaker settings
BEAKER_SERVER = "https://beaker.example.com"

# Set BEAKER_OWNER and BEAKER_PASS or you can use kerberos auth
BEAKER_OWNER = None
BEAKER_PASS = None

BEAKER_DEFAULT_PACKAGES = (
    "vim", "gcc", "make", "nfs-utils", "wget", "libxml2-python",
)


BKR_SYSTEM_PASS = None
BKR_SYSTEM_USER = None

RESERVE_TEST = "/distribution/reservesys"

# If you want to change directory with repositories,
# don't forget changed it in /var/www/gitweb/gitweb_config.perl
REPOSITORIES_GIT = {
    "~":
        ("/tests",),
}

PAGINATOR_OBJECTS_ONPAGE = 20
PAGINATOR_OBJECTS_ONHOMEPAGE = 10
PREVIOUS_DAYS = 9
CHECK_COMMMITS_PREVIOUS_DAYS = 7


GRAPPELLI_ADMIN_TITLE = "<a href='/' >Green Tea</a>"

GRAPPELLI_INDEX_DASHBOARD = 'dashboard.CustomIndexDashboard'

TEMPLATE_FOOTER = "Created by Satellite QA Team in 2013-2015"

REST_FRAMEWORK = {
    # Use Django's standard `django.contrib.auth` permissions,
    # or allow read-only access for unauthenticated users.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.DjangoModelPermissionsOrAnonReadOnly'
    ]
}