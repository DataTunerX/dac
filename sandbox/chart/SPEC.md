# Spec: DAC Sandbox Helm Chart

## Objective

独立 Helm chart，**一个 Pod IP** 模拟企业给 DAC 扫描的主机。与平台 `installer/dac` 解耦。

## Topology

```
STS dac-sandbox-0（唯一扫描目标 IP）
  mysql:3306
  postgres:5432          ← 演示库 + odoo_demo + saleor
  redis:6379
  minio:9000/9001
  fileserver:8000
  saleor-api:8001
  saleor-dashboard:9002   ← 避开 minio:9000
  odoo:8069
  gitlab:8929
  boutique-frontend:8080 + 全部 Boutique 微服务（127.0.0.1 互联）

Jobs（非长期扫描目标）
  minio-seed / gitlab-seed / saleor-populatedb
```

## Install

```bash
make offline-prep
make apply
make scan-targets   # 只需 STS 一个 IP
```

## Scan ports

`3306,5432,6379,8000,8001,8069,8080,8929,9000,9001,9002`

## Non-goals

- 不进平台 Helm
- 不拆多 Pod 演示（刻意单 IP）
