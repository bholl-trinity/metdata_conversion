mod aermet_runner;
mod aerminute;
mod aersurface;
mod completeness;
mod download;
mod geocode;
mod ghcnh_to_isd;
mod http_client;
mod igra;
mod project;
mod server;
mod stations;

use std::net::TcpListener;

#[tokio::main]
async fn main() {
    // Create required directories next to the executable
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."));

    for dir in &["projects", "data", "bin"] {
        std::fs::create_dir_all(exe_dir.join(dir)).ok();
    }

    // Find a free port
    let port = find_free_port().unwrap_or(5000);
    let addr = format!("127.0.0.1:{port}");

    println!("============================================================");
    println!("  AERMET Automation Tool");
    println!("  Starting server at http://{addr}");
    println!("============================================================");
    println!();
    println!("  Your browser should open automatically.");
    println!("  If not, open: http://{addr}");
    println!();
    println!("  Press Ctrl+C to stop.");
    println!("============================================================");

    // Open browser
    let url = format!("http://{addr}");
    let _ = open::that(&url);

    // Start server
    let app = server::create_router();
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .expect("Failed to bind address");

    axum::serve(listener, app)
        .await
        .expect("Server error");
}

fn find_free_port() -> Option<u16> {
    TcpListener::bind("127.0.0.1:0")
        .ok()
        .map(|l| l.local_addr().unwrap().port())
}
