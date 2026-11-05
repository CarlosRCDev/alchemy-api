USER=diablocharly
IMAGE="${USER}/sqlalchemy-rest-api" deployments/build.sh
IMAGE="${USER}/sqlalchemy-rest-api" deployments/push.sh
# IMAGE="${USER}/sqlalchemy-rest-api" deployments/push.sh postgres
