REG=release.daocloud.io/dac

docker pull frappe/erpnext:v15.95.0
docker pull mariadb:10.6
docker pull redis:6.2-alpine

docker tag frappe/erpnext:v15.95.0  $REG/erpnext:v15.95.0
docker tag mariadb:10.6             $REG/mariadb:10.6
docker tag redis:6.2-alpine         $REG/redis:6.2-alpine

docker push $REG/erpnext:v15.95.0
docker push $REG/mariadb:10.6
docker push $REG/redis:6.2-alpine
