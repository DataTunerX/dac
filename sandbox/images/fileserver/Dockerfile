# DAC sandbox fileserver — HTTP 静态文件服务，端口 8000
# 给 DAC unstructured descriptor 走 fileserver 路径用：
#   data-sinkers fileserver_reader 走 GET http://host:port/{filename}
#
# 构建上下文必须是 sandbox/ 根目录:
#   docker build -t release.daocloud.io/dac/sandbox-fileserver:v0.10.0 -f images/fileserver/Dockerfile .

FROM nginx:1.27-alpine

# 默认 nginx 监听 80 + 不开 autoindex，覆盖成 8000 + autoindex on
COPY images/fileserver/default.conf /etc/nginx/conf.d/default.conf

# 把 seed/files/ 全部静态托管在 /
COPY seed/files /usr/share/nginx/html

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=10 \
  CMD wget -q --spider http://127.0.0.1:8000/ || exit 1
