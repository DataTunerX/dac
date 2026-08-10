{{/*
  Extra STS containers: Saleor Dashboard + Online Boutique (all on one Pod IP).
  Boutique ports remapped where upstream reused 8080/50051 across services.
*/}}
{{- define "dac-sandbox.stsExtraContainers" -}}
# ---------- Saleor Dashboard (9002; 9000=minio) ----------
- name: saleor-dashboard
  image: {{ include "dac-sandbox.saleorDashboardImage" . }}
  imagePullPolicy: IfNotPresent
  env:
    - name: API_URL
      value: "/graphql/"
    - name: APP_MOUNT_URI
      value: "/dashboard/"
  ports:
    - name: saleor-ui
      containerPort: 9002
  volumeMounts:
    - name: saleor-dashboard-nginx
      mountPath: /etc/nginx/conf.d/default.conf
      subPath: default.conf
  readinessProbe:
    httpGet:
      path: /dashboard/
      port: 9002
    initialDelaySeconds: 15
    periodSeconds: 10
  resources:
    {{- toYaml .Values.resources.saleorDashboard | nindent 4 }}

# ---------- Online Boutique (localhost mesh) ----------
- name: boutique-currency
  image: {{ printf "%s/boutique-currencyservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "7000"
    - name: DISABLE_PROFILER
      value: "1"
  ports:
    - { name: b-currency, containerPort: 7000 }
  readinessProbe:
    grpc: { port: 7000 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-catalog
  image: {{ printf "%s/boutique-productcatalogservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "3550"
    - name: DISABLE_PROFILER
      value: "1"
  ports:
    - { name: b-catalog, containerPort: 3550 }
  readinessProbe:
    grpc: { port: 3550 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-cart
  image: {{ printf "%s/boutique-cartservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: REDIS_ADDR
      value: "127.0.0.1:6379"
    - name: PORT
      value: "7070"
  ports:
    - { name: b-cart, containerPort: 7070 }
  readinessProbe:
    grpc: { port: 7070 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-shipping
  image: {{ printf "%s/boutique-shippingservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "50051"
    - name: DISABLE_PROFILER
      value: "1"
  ports:
    - { name: b-ship, containerPort: 50051 }
  readinessProbe:
    grpc: { port: 50051 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-payment
  image: {{ printf "%s/boutique-paymentservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "50052"
    - name: DISABLE_PROFILER
      value: "1"
  ports:
    - { name: b-pay, containerPort: 50052 }
  readinessProbe:
    grpc: { port: 50052 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-email
  image: {{ printf "%s/boutique-emailservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "5000"
    - name: DISABLE_PROFILER
      value: "1"
  ports:
    - { name: b-email, containerPort: 5000 }
  readinessProbe:
    grpc: { port: 5000 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-recommend
  image: {{ printf "%s/boutique-recommendationservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "8081"
    - name: PRODUCT_CATALOG_SERVICE_ADDR
      value: "127.0.0.1:3550"
    - name: DISABLE_PROFILER
      value: "1"
  ports:
    - { name: b-rec, containerPort: 8081 }
  readinessProbe:
    grpc: { port: 8081 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-ads
  image: {{ printf "%s/boutique-adservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "9555"
  ports:
    - { name: b-ads, containerPort: 9555 }
  readinessProbe:
    grpc: { port: 9555 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-checkout
  image: {{ printf "%s/boutique-checkoutservice:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "5050"
    - name: PRODUCT_CATALOG_SERVICE_ADDR
      value: "127.0.0.1:3550"
    - name: SHIPPING_SERVICE_ADDR
      value: "127.0.0.1:50051"
    - name: PAYMENT_SERVICE_ADDR
      value: "127.0.0.1:50052"
    - name: EMAIL_SERVICE_ADDR
      value: "127.0.0.1:5000"
    - name: CURRENCY_SERVICE_ADDR
      value: "127.0.0.1:7000"
    - name: CART_SERVICE_ADDR
      value: "127.0.0.1:7070"
  ports:
    - { name: b-checkout, containerPort: 5050 }
  readinessProbe:
    grpc: { port: 5050 }
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}

- name: boutique-frontend
  image: {{ printf "%s/boutique-frontend:%s" .Values.global.imageRegistry .Values.boutique.imageTag }}
  imagePullPolicy: IfNotPresent
  securityContext:
    allowPrivilegeEscalation: false
    runAsNonRoot: true
    runAsUser: 1000
    capabilities: { drop: ["ALL"] }
  env:
    - name: PORT
      value: "8080"
    - name: PRODUCT_CATALOG_SERVICE_ADDR
      value: "127.0.0.1:3550"
    - name: CURRENCY_SERVICE_ADDR
      value: "127.0.0.1:7000"
    - name: CART_SERVICE_ADDR
      value: "127.0.0.1:7070"
    - name: RECOMMENDATION_SERVICE_ADDR
      value: "127.0.0.1:8081"
    - name: SHIPPING_SERVICE_ADDR
      value: "127.0.0.1:50051"
    - name: CHECKOUT_SERVICE_ADDR
      value: "127.0.0.1:5050"
    - name: AD_SERVICE_ADDR
      value: "127.0.0.1:9555"
    # Required by newer frontend images (mustMapEnv); assistant itself is optional
    # and not deployed in the sandbox — keep ENABLE_ASSISTANT unset/false.
    - name: SHOPPING_ASSISTANT_SERVICE_ADDR
      value: "127.0.0.1:80"
    - name: ENABLE_PROFILER
      value: "0"
  ports:
    - { name: boutique, containerPort: 8080 }
  readinessProbe:
    httpGet:
      path: /_healthz
      port: 8080
      httpHeaders:
        - name: Cookie
          value: shop_session-id=x-readiness-probe
    initialDelaySeconds: 10
  resources:
    {{- toYaml .Values.resources.boutique | nindent 4 }}
{{- end }}
