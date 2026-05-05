-- DAC sandbox: 创建演示用 databases 和统一只读账号 dac/dacpass
CREATE DATABASE IF NOT EXISTS dac_sandbox          DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS dactest              DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS test1                DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS corporate_hr         DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS online_edu_bi_test   DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS sakila               DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'dac'@'%' IDENTIFIED BY 'dacpass';
GRANT ALL PRIVILEGES ON dac_sandbox.*        TO 'dac'@'%';
GRANT ALL PRIVILEGES ON dactest.*            TO 'dac'@'%';
GRANT ALL PRIVILEGES ON test1.*              TO 'dac'@'%';
GRANT ALL PRIVILEGES ON corporate_hr.*       TO 'dac'@'%';
GRANT ALL PRIVILEGES ON online_edu_bi_test.* TO 'dac'@'%';
GRANT ALL PRIVILEGES ON sakila.*             TO 'dac'@'%';
FLUSH PRIVILEGES;
