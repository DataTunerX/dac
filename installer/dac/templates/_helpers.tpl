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

{{/*
Common Redis CLI args for agent containers
Usage: {{ include "dac.redisArgs" . }}
*/}}
{{- define "dac.redisArgs" -}}
- "--redis-host"
- {{ include "dac.redis.serviceName" . | quote }}
- "--redis-port"
- {{ .Values.redis.port | quote }}
- "--redis-db"
- {{ .redisDB | default "0" | quote }}
- "--password"
- {{ .Values.redis.password | quote }}
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
