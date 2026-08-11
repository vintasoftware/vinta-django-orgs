DEBUG = True
USE_TZ = True

# The example apps ship migrations created with AutoField primary keys.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'lq54#hsg57uikn$*=dk+4t$(zg*2k6!^5+8opzp^lsgyp$s-rj'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

ROOT_URLCONF = 'tests.urls'

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sites',
    'django.contrib.sessions',
    'django.contrib.messages',
    'rest_framework',
    'organizations.apps.OrganizationsConfig',
    'exampleproject.articles',
    'exampleproject.lectures',
    'organizations_custom_data.apps.OrganizationsCustomDataConfig',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'organizations.middleware.OrganizationMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ``django.contrib.admin`` is installed so the admin classes this library
# ships are actually exercised; it checks for these at startup.
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

REST_FRAMEWORK = {
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
}


AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'organizations.auth_backends.OrganizationModelBackend',
    'organizations_custom_data.auth_backends.OrganizationSpecificTablesBackend',
]
