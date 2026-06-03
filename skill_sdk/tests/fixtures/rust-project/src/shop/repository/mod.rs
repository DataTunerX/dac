pub mod repository_trait;
pub mod inmemory;
pub mod postgres;

pub use repository_trait::Repository;
pub use inmemory::InMemoryRepository;
pub use postgres::PostgresRepository;
