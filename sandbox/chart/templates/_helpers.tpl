{{/*
Expand the name of the chart.
*/}}
{{- define "dac-sandbox.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "dac-sandbox.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- include "dac-sandbox.name" . }}
{{- end }}
{{- end }}

{{- define "dac-sandbox.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "dac-sandbox.labels" -}}
helm.sh/chart: {{ include "dac-sandbox.chart" . }}
{{ include "dac-sandbox.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: dac-sandbox
{{- end }}

{{- define "dac-sandbox.selectorLabels" -}}
app.kubernetes.io/name: {{ include "dac-sandbox.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: dac-sandbox
{{- end }}

{{/*
Image helpers — registry/repo:tag
*/}}
{{- define "dac-sandbox.image" -}}
{{- $registry := .root.Values.global.imageRegistry -}}
{{- printf "%s/%s:%s" $registry .repo .tag -}}
{{- end }}

{{- define "dac-sandbox.sandboxImage" -}}
{{- printf "%s/%s:%s" .Values.global.imageRegistry .name .Values.global.imageTag -}}
{{- end }}

{{- define "dac-sandbox.saleorImage" -}}
{{- printf "%s/saleor:%s" .Values.global.imageRegistry .Values.saleor.imageTag -}}
{{- end }}

{{- define "dac-sandbox.saleorDashboardImage" -}}
{{- printf "%s/saleor-dashboard:%s" .Values.global.imageRegistry .Values.saleor.dashboardImageTag -}}
{{- end }}

{{- define "dac-sandbox.odooImage" -}}
{{- printf "%s/odoo:%s" .Values.global.imageRegistry .Values.odoo.imageTag -}}
{{- end }}

{{- define "dac-sandbox.redisImage" -}}
{{- printf "%s/%s:%s" .Values.global.imageRegistry .Values.redis.repository .Values.redis.tag -}}
{{- end }}

{{- define "dac-sandbox.minioImage" -}}
{{- printf "%s/%s:%s" .Values.global.imageRegistry .Values.minio.repository .Values.minio.tag -}}
{{- end }}

{{- define "dac-sandbox.gitlabImage" -}}
{{- printf "%s/%s:%s" .Values.global.imageRegistry .Values.gitlab.repository .Values.gitlab.tag -}}
{{- end }}

{{- define "dac-sandbox.alpineImage" -}}
{{- printf "%s/%s:%s" .Values.global.imageRegistry .Values.alpine.repository .Values.alpine.tag -}}
{{- end }}

{{- define "dac-sandbox.boutiqueImage" -}}
{{- printf "%s/boutique-%s:%s" .root.Values.global.imageRegistry .name .root.Values.boutique.imageTag -}}
{{- end }}

{{- define "dac-sandbox.saleorDatabaseUrl" -}}
{{- $c := .Values.credentials -}}
{{- printf "postgres://%s:%s@127.0.0.1:5432/%s" $c.saleorUser $c.saleorPassword $c.saleorDatabase -}}
{{- end }}

{{- define "dac-sandbox.saleorDatabaseUrlExternal" -}}
{{- $c := .Values.credentials -}}
{{- printf "postgres://%s:%s@postgres:5432/%s" $c.saleorUser $c.saleorPassword $c.saleorDatabase -}}
{{- end }}
