{{/*
Expand the name of the chart.
*/}}
{{- define "dac.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Optional resource name prefix.
Default: no prefix (empty). Set fullnameOverride to add one.
Example: --set fullnameOverride=prod  →  resources become prod-frontend, prod-mysql, etc.
*/}}
{{- define "dac.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Build a resource name: optional prefix + component name.
Usage: {{ include "dac.componentName" (dict "context" . "name" "frontend") }}
  - default:                  "frontend"
  - fullnameOverride: "prod": "prod-frontend"
*/}}
{{- define "dac.componentName" -}}
{{- $prefix := include "dac.fullname" .context -}}
{{- if $prefix -}}
{{- printf "%s-%s" $prefix .name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .name -}}
{{- end -}}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "dac.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels (applied to all resources).
*/}}
{{- define "dac.labels" -}}
helm.sh/chart: {{ include "dac.chart" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: dac
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Selector labels for a specific component (immutable after creation).
Usage: {{ include "dac.selectorLabels" (dict "context" . "name" "component-name") }}
*/}}
{{- define "dac.selectorLabels" -}}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
{{- end }}

{{/*
Component labels combining common + selector.
Usage: {{ include "dac.componentLabels" (dict "context" . "name" "component-name") }}
*/}}
{{- define "dac.componentLabels" -}}
{{ include "dac.labels" .context }}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/component: {{ .name }}
{{- end }}

{{/* ==== Service name helpers ==== */}}

{{- define "dac.mysql.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "mysql") -}}
{{- end }}

{{- define "dac.redis.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "redis") -}}
{{- end }}

{{- define "dac.pgvector.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "pgvector") -}}
{{- end }}

{{- define "dac.neo4j.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "neo4j") -}}
{{- end }}

{{/* ==== Middleware external-or-built-in resolvers ====
  Each helper returns the external value when <svc>.external.host is set,
  otherwise falls back to the built-in StatefulSet Service DNS.
*/}}

{{- define "dac.mysql.host" -}}
{{- if .Values.mysql.external.host }}
{{- .Values.mysql.external.host }}
{{- else }}
{{- printf "%s.%s.svc.cluster.local" (include "dac.mysql.serviceName" .) .Release.Namespace }}
{{- end }}
{{- end }}

{{- define "dac.mysql.port" -}}
{{- if .Values.mysql.external.host }}
{{- .Values.mysql.external.port | default 3306 | toString }}
{{- else }}
{{- .Values.mysql.port | toString }}
{{- end }}
{{- end }}

{{- define "dac.mysql.password" -}}
{{- if .Values.mysql.external.host }}
{{- .Values.mysql.external.password }}
{{- else }}
{{- .Values.mysql.rootPassword }}
{{- end }}
{{- end }}

{{- define "dac.redis.host" -}}
{{- if .Values.redis.external.host }}
{{- .Values.redis.external.host }}
{{- else }}
{{- printf "%s.%s.svc.cluster.local" (include "dac.redis.serviceName" .) .Release.Namespace }}
{{- end }}
{{- end }}

{{- define "dac.redis.port" -}}
{{- if .Values.redis.external.host }}
{{- .Values.redis.external.port | default 6379 | toString }}
{{- else }}
{{- .Values.redis.port | toString }}
{{- end }}
{{- end }}

{{- define "dac.redis.password" -}}
{{- if .Values.redis.external.host }}
{{- .Values.redis.external.password }}
{{- else }}
{{- .Values.redis.password }}
{{- end }}
{{- end }}

{{- define "dac.pgvector.host" -}}
{{- if .Values.pgvector.external.host }}
{{- .Values.pgvector.external.host }}
{{- else }}
{{- printf "%s.%s.svc.cluster.local" (include "dac.pgvector.serviceName" .) .Release.Namespace }}
{{- end }}
{{- end }}

{{- define "dac.pgvector.port" -}}
{{- if .Values.pgvector.external.host }}
{{- .Values.pgvector.external.port | default 5432 | toString }}
{{- else }}
{{- .Values.pgvector.port | toString }}
{{- end }}
{{- end }}

{{- define "dac.pgvector.password" -}}
{{- if .Values.pgvector.external.host }}
{{- .Values.pgvector.external.password }}
{{- else }}
{{- .Values.pgvector.password }}
{{- end }}
{{- end }}

{{- define "dac.neo4j.host" -}}
{{- if .Values.neo4j.external.host }}
{{- .Values.neo4j.external.host }}
{{- else }}
{{- printf "%s.%s.svc.cluster.local" (include "dac.neo4j.serviceName" .) .Release.Namespace }}
{{- end }}
{{- end }}

{{- define "dac.neo4j.boltPort" -}}
{{- if .Values.neo4j.external.host }}
{{- .Values.neo4j.external.boltPort | default .Values.neo4j.boltPort | default 7687 | toString }}
{{- else }}
{{- .Values.neo4j.boltPort | toString }}
{{- end }}
{{- end }}

{{- define "dac.neo4j.password" -}}
{{- if .Values.neo4j.external.host }}
{{- .Values.neo4j.external.password }}
{{- else }}
{{- .Values.neo4j.password }}
{{- end }}
{{- end }}

{{/* Bolt URL: auto-built from neo4j.external.host when set; else dataServices.config.neo4j.boltUrl */}}
{{- define "dac.neo4j.boltUrl" -}}
{{- if .Values.neo4j.external.host }}
{{- printf "bolt://%s:%s" .Values.neo4j.external.host (include "dac.neo4j.boltPort" .) }}
{{- else }}
{{- .Values.dataServices.config.neo4j.boltUrl }}
{{- end }}
{{- end }}

{{/* neo4j:// URL for mem0 graph; same external/built-in resolution as boltUrl */}}
{{- define "dac.neo4j.neo4jUrl" -}}
{{- if .Values.neo4j.external.host }}
{{- printf "neo4j://%s:%s" .Values.neo4j.external.host (include "dac.neo4j.boltPort" .) }}
{{- else }}
{{- .Values.dataServices.config.neo4j.neo4jUrl }}
{{- end }}
{{- end }}

{{- define "dac.dataServices.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "data-services") -}}
{{- end }}

{{- define "dac.dataServices.url" -}}
{{- printf "http://%s:%v" (include "dac.dataServices.serviceName" .) (.Values.dataServices.service.port | default 8000) }}
{{- end }}

{{- define "dac.orchestratorRegistry.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "orchestrator-registry") -}}
{{- end }}

{{- define "dac.bizOrchestratorRegistry.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "biz-orchestrator-registry") -}}
{{- end }}

{{- define "dac.bizRoutingAgent.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "biz-routing-agent") -}}
{{- end }}

{{- define "dac.bizChartAgent.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "biz-chart-agent") -}}
{{- end }}

{{- define "dac.bizSkillAgent.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "biz-skill-agent") -}}
{{- end }}

{{- define "dac.skillHub.serviceName" -}}
{{- include "dac.componentName" (dict "context" . "name" "skill-hub") -}}
{{- end }}

{{- define "dac.skillHub.url" -}}
{{- printf "http://%s.%s.svc.cluster.local:%v" (include "dac.skillHub.serviceName" .) .Release.Namespace (.Values.skillHub.service.port | default 8000) -}}
{{- end }}

{{/*
Common Redis CLI args for agent containers.
Usage: {{ include "dac.redisArgs" (dict "context" . "redisDB" "0") }}
*/}}
{{- define "dac.redisArgs" -}}
- "--redis-host"
- {{ include "dac.redis.host" .context | quote }}
- "--redis-port"
- {{ include "dac.redis.port" .context | quote }}
- "--redis-db"
- {{ .redisDB | default "0" | quote }}
- "--password"
- {{ include "dac.redis.password" .context | quote }}
{{- end }}

{{/*
Common LLM CLI args for agent containers
Usage: {{ include "dac.llmArgs" . }}
*/}}
{{- define "dac.llmArgs" -}}
- "--provider"
- {{ .Values.global.llm.provider | quote }}
- "--api-key"
- {{ .Values.global.llm.apiKey | quote }}
- "--base-url"
- {{ .Values.global.llm.baseUrl | quote }}
- "--model"
- {{ .Values.global.llm.model | quote }}
{{- end }}

{{/*
Optional Langfuse env vars for LLM tracing (inject under container env:)
Usage: {{- include "dac.langfuseEnv" . | nindent 12 }}
*/}}
{{- define "dac.langfuseEnv" -}}
{{- if and .Values.global.langfuse .Values.global.langfuse.enabled }}
{{- $dac := .Values.executionEngine.dacConfig | default dict }}
{{- $lf := .Values.global.langfuse }}
- name: LANGFUSE_BASE_URL
  value: {{ coalesce $dac.observationBaseUrl $lf.baseUrl | quote }}
- name: LANGFUSE_SECRET_KEY
  value: {{ coalesce $dac.observationSecretKey $lf.secretKey | quote }}
- name: LANGFUSE_PUBLIC_KEY
  value: {{ coalesce $dac.observationPublicKey $lf.publicKey | quote }}
{{- end }}
{{- end }}

{{/*
Langfuse observation keys for dac-configuration / dd-configuration ConfigMap data:
only when global.langfuse.enabled; dacConfig.observation* overrides global.langfuse.*
Usage: {{- include "dac.observationConfigMapData" . | nindent 2 }}
*/}}
{{- define "dac.observationConfigMapData" -}}
{{- if and .Values.global.langfuse .Values.global.langfuse.enabled }}
{{- $dac := .Values.executionEngine.dacConfig | default dict }}
{{- $lf := .Values.global.langfuse }}
{{- $obsUrl := coalesce $dac.observationBaseUrl $lf.baseUrl }}
{{- $obsSecret := coalesce $dac.observationSecretKey $lf.secretKey }}
{{- $obsPublic := coalesce $dac.observationPublicKey $lf.publicKey }}
{{- if $obsUrl }}
observation-base-url: {{ $obsUrl | quote }}
{{- end }}
{{- if $obsSecret }}
observation-secret-key: {{ $obsSecret | quote }}
{{- end }}
{{- if $obsPublic }}
observation-public-key: {{ $obsPublic | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Image reference helper
Usage: {{ include "dac.image" (dict "registry" .Values.global.imageRegistry "repository" "data-services" "tag" .Values.dataServices.image.tag) }}
*/}}
{{- define "dac.image" -}}
{{- if .registry }}
{{- printf "%s/%s:%s" .registry .repository .tag }}
{{- else }}
{{- printf "%s:%s" .repository .tag }}
{{- end }}
{{- end }}

{{/*
Generate initContainers that wait for TCP services to be ready.
Usage:
  initContainers:
    {{- include "dac.initWait" (list (dict "name" "redis" "host" "..." "port" "6379")) | nindent 4 }}
    {{- include "dac.initWait" (list (dict "name" "mysql" "host" "..." "port" "3306")) | nindent 4 }}
*/}}
{{- define "dac.initWait" }}
{{- range . }}
- name: wait-for-{{ .name }}
  image: registry.cn-shanghai.aliyuncs.com/jamesxiong/busybox:1.36
  imagePullPolicy: IfNotPresent
  command: ["sh", "-c"]
  args:
    - |
      until nc -z {{ .host }} {{ .port }}; do
        echo "waiting for {{ .name }} at {{ .host }}:{{ .port }}..."
        sleep 2
      done
      echo "{{ .name }} is ready"
{{- end }}
{{- end }}
