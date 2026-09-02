pub mod artifact;
pub mod assertion;
pub mod decision;
pub mod embedding;
pub mod entity;
pub mod event;
pub mod evidence;
pub mod gateway_backend;
pub mod governance;
pub mod memory;
pub mod ontology;
pub mod search;
pub mod snapshot;
pub mod state;
pub mod stream_filter;
pub mod wiki;

pub mod proto {
    tonic::include_proto!("tdb.gateway.backend.v1");
}
