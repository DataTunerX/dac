package dto

import (
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

type NamespaceResponse struct {
	Name string `json:"name"`
}

func ToNamespaceResponse(ns *entity.Namespace) NamespaceResponse {
	if ns == nil {
		return NamespaceResponse{}
	}
	return NamespaceResponse{Name: ns.Name}
}

