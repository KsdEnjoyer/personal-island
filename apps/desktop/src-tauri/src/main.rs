#![cfg_attr(windows, windows_subsystem = "windows")]

fn main() {
    #[cfg(target_os = "linux")]
    set_linux_window_backend();

    personal_island_desktop::run()
}

#[cfg(target_os = "linux")]
fn set_linux_window_backend() {
    let has_display = |name| std::env::var_os(name).is_some_and(|value| !value.is_empty());
    if !has_display("GDK_BACKEND") && has_display("WAYLAND_DISPLAY") && has_display("DISPLAY") {
        // Native Wayland does not allow GTK to position a regular window at
        // the top of the monitor. Keep Wayland available for desktop portals.
        std::env::set_var("GDK_BACKEND", "x11,wayland");
    }
}
