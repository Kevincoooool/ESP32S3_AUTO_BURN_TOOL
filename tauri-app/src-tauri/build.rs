fn main() {
    let target = std::env::var("TARGET").unwrap_or_else(|_| "unknown-target".into());
    println!("cargo:rustc-env=BUILD_TARGET={target}");
    tauri_build::build()
}
