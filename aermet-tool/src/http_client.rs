/// Shared HTTP client for all outbound requests.
use reqwest::Client;
use std::sync::OnceLock;

static CLIENT: OnceLock<Client> = OnceLock::new();

pub fn client() -> &'static Client {
    CLIENT.get_or_init(|| {
        Client::builder()
            .user_agent("AERMET-Automation-Tool/1.0")
            .build()
            .expect("failed to build HTTP client")
    })
}
