# Configuration
HOST = 'http://trunkimax.loc'

# absolute or relative path to access nginx log
PATH_TO_NGINX_ACCESS_LOG = 'access.log'

# Absolute or relative path to directory were is putting log files
PATH_TO_LOG = 'logs/'

# count latest bites from access log for analize (zero - parsing all file)
COUNT_LATEST_BITES = 0.1*1024*1024

# count threading
COUNT_THREADING = 8

# print current status every PRINT_STATUS_COUNT urls
PRINT_STATUS_COUNT = 1

# credentional for Django sites
DJANGO_ADMIN_LOGIN = 'dev'
DJANGO_ADMIN_PASSWORD = 'pool'
