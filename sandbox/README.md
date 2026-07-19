# DAC Sandbox

模拟**企业给一个 IP**：全部扫描目标跑在 **同一个 StatefulSet Pod** 里。  
独立 Helm chart，与平台 [`installer/dac`](../installer/README.md) 解耦。

> 样本数据仅供演示，勿用于生产。

---

## 架构

```
┌──────────────────────── dac-sandbox-0（一个 Pod IP）────────────────────────┐
│  mysql:3306   postgres:5432   redis:6379   minio:9000/9001                   │
│  fileserver:8000   saleor-api:8001   saleor-dashboard:9002                   │
│  odoo:8069   gitlab:8929   boutique-frontend:8080 (+ Boutique 微服务)         │
│  postgres 共用：演示库 + odoo_demo + saleor                                   │
└─────────────────────────────────────────────────────────────────────────────┘
         Jobs: minio-seed / gitlab-seed / saleor-populatedb
```

探测时**只填 STS 这一个 IP** 即可。

| 端口 | 服务 |
|------|------|
| 3306 | MySQL |
| 5432 | Postgres（共用） |
| 6379 | Redis |
| 8000 | FileServer |
| 8001 | Saleor API |
| 8069 | Odoo |
| 8080 | Online Boutique 店面 |
| 8929 | GitLab |
| 9000 | MinIO S3 |
| 9001 | MinIO Console |
| 9002 | Saleor Dashboard（路径 `/dashboard/`） |

DNS（同 ns）：`mysql` / `postgres` / `redis` / `fileserver` / `gitlab` / `odoo` / `saleor-api` / `saleor-dashboard` / `frontend` …

---

## 安装

```bash
cd sandbox
make offline-prep   # 有网机一次
make apply          # helm install ./chart -n dac-sandbox
make verify
make scan-targets
```

卸载：`make uninstall`

资源建议：≥ **10–12 GiB** 可用内存（GitLab + Odoo + Saleor + Boutique 同 Pod）。

---

## 资产探测

```bash
make scan-targets
```

| 字段 | 值 |
|------|-----|
| 目标 | **仅** `dac-sandbox-0` 的 Pod IP |
| 端口 | `3306,5432,6379,8000,8001,8069,8080,8929,9000,9001,9002` |

---

## 凭据（演示）

| 组件 | 凭据 |
|------|------|
| MySQL | `root` / `dacpass` |
| Postgres | `postgres` / `dacpass`；`odoo`/`odopass`；`saleor`/`saleor` |
| MinIO | `dac` / `dacpassword` |
| GitLab | `root` / `dacpassword` |
| Saleor | `admin@example.com` / `admin` |

示例 CR：`examples/dac-cr/`（host 用上表 DNS 或 Pod IP）。

详见 [`chart/SPEC.md`](chart/SPEC.md)、[`build.md`](build.md)。
