//! URI file lists shared by Linux file managers through the clipboard.
use std::{
    io::{Read, Write},
    os::fd::AsRawFd,
    path::Path,
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};

pub const MAX_FILES: usize = 64;
const MAX_BYTES: usize = 256 * 1024;

fn read_type(mime: &str, limit: usize) -> Result<Option<Vec<u8>>, String> {
    let mut command = if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        let mut command = Command::new("wl-paste");
        command.args(["--type", mime]);
        if mime.starts_with("text/") {
            command.arg("--no-newline");
        }
        command
    } else {
        let mut command = Command::new("xclip");
        command.args(["-selection", "clipboard", "-out", "-t", mime]);
        command
    };
    let child = match command.stdout(Stdio::piped()).stderr(Stdio::null()).spawn() {
        Ok(child) => child,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    read_child_limited(child, limit, Duration::from_secs(2))
}

fn read_child_limited(
    mut child: Child,
    limit: usize,
    timeout: Duration,
) -> Result<Option<Vec<u8>>, String> {
    let deadline = Instant::now() + timeout;
    let mut stdout = child.stdout.take().ok_or("Нет вывода команды буфера")?;
    let descriptor = stdout.as_raw_fd();
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(descriptor, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0
    {
        let _ = child.kill();
        let _ = child.wait();
        return Err("Не удалось настроить чтение буфера обмена".into());
    }
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 8192];
    loop {
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(None);
        }
        match stdout.read(&mut buffer) {
            Ok(0) => break,
            Ok(size) if size <= limit.saturating_sub(bytes.len()) => {
                bytes.extend_from_slice(&buffer[..size]);
                continue;
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Ok(_) | Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Ok(None);
            }
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(None);
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    drop(stdout);
    loop {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            return Ok(status.success().then_some(bytes));
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(None);
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

pub(crate) fn decode_uri(uri: &str) -> Option<String> {
    let encoded = uri.strip_prefix("file://")?;
    let encoded = encoded.strip_prefix("localhost").unwrap_or(encoded);
    if !encoded.starts_with('/') {
        return None;
    }
    let mut result = Vec::new();
    let mut bytes = encoded.bytes();
    while let Some(byte) = bytes.next() {
        if byte == b'%' {
            let hex = |value: u8| (value as char).to_digit(16).map(|n| n as u8);
            result.push(hex(bytes.next()?)? * 16 + hex(bytes.next()?)?);
        } else {
            result.push(byte);
        }
    }
    let path = String::from_utf8(result).ok()?;
    (!path.contains('\0') && Path::new(&path).is_absolute()).then_some(path)
}

pub(crate) fn parse_uris(input: &[u8]) -> Option<Vec<String>> {
    let input = std::str::from_utf8(input).ok()?;
    let mut paths = Vec::new();
    for line in input.lines().map(str::trim).filter(|line| !line.is_empty()) {
        if line.starts_with('#') || line == "copy" || line == "cut" {
            continue;
        }
        let path = decode_uri(line)?;
        paths.push(path);
        if paths.len() > MAX_FILES {
            return None;
        }
    }
    (!paths.is_empty()).then_some(paths)
}

pub fn read_files() -> Result<Option<Vec<String>>, String> {
    Ok(read_type("text/uri-list", MAX_BYTES)?.and_then(|bytes| parse_uris(&bytes)))
}

pub fn read_png() -> Result<Option<Vec<u8>>, String> {
    read_type("image/png", 8 * 1024 * 1024)
}

fn encode_uri(path: &str) -> String {
    let mut result = String::from("file://");
    for byte in path.bytes() {
        if byte.is_ascii_alphanumeric() || b"/-._~".contains(&byte) {
            result.push(byte as char);
        } else {
            result.push_str(&format!("%{byte:02X}"));
        }
    }
    result
}

pub fn write_files(_: isize, paths: &[String]) -> Result<(), String> {
    if paths.is_empty() || paths.len() > MAX_FILES {
        return Err("Можно скопировать от 1 до 64 файлов".into());
    }
    let mut uris = String::new();
    for path in paths {
        if !Path::new(path).is_absolute() || path.contains('\0') {
            return Err("Неверный путь файла".into());
        }
        if !Path::new(path).exists() {
            return Err(format!("Файл перемещён или удалён: {path}"));
        }
        uris.push_str(&encode_uri(path));
        uris.push_str("\r\n");
    }
    if uris.len() > MAX_BYTES {
        return Err("Слишком длинный список файлов".into());
    }
    let mut command = if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        let mut command = Command::new("wl-copy");
        command.args(["--type", "text/uri-list"]);
        command
    } else {
        let mut command = Command::new("xclip");
        command.args(["-selection", "clipboard", "-in", "-t", "text/uri-list"]);
        command
    };
    let child = command
        .stdin(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| {
            format!("Для копирования файлов установи wl-clipboard или xclip: {error}")
        })?;
    write_child_limited(child, uris.as_bytes(), Duration::from_secs(3))
}

fn write_child_limited(mut child: Child, bytes: &[u8], timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    let mut stdin = child.stdin.take().ok_or("Нет ввода команды буфера")?;
    let descriptor = stdin.as_raw_fd();
    let flags = unsafe { libc::fcntl(descriptor, libc::F_GETFL) };
    if flags < 0 || unsafe { libc::fcntl(descriptor, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0
    {
        let _ = child.kill();
        let _ = child.wait();
        return Err("Не удалось настроить запись в буфер обмена".into());
    }
    let mut written = 0;
    while written < bytes.len() {
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("Буфер обмена не ответил вовремя".into());
        }
        match stdin.write(&bytes[written..]) {
            Ok(0) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Не удалось записать список файлов в буфер".into());
            }
            Ok(size) => written += size,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {}
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error.to_string());
            }
        }
    }
    drop(stdin);
    loop {
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            return if status.success() {
                Ok(())
            } else {
                Err("Не удалось скопировать файлы в буфер обмена".into())
            };
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err("Буфер обмена не ответил вовремя".into());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn file_uris_keep_unicode_and_reject_remote_hosts() {
        let path = "/home/user/Фото и текст.png";
        assert_eq!(
            parse_uris(format!("copy\n{}\r\n", encode_uri(path)).as_bytes()),
            Some(vec![path.into()])
        );
        assert_eq!(parse_uris(b"file://evil.example/etc/passwd\n"), None);
        assert_eq!(parse_uris(b"file:///tmp/%00secret\n"), None);
    }

    #[test]
    fn clipboard_owner_that_never_sends_data_does_not_block_monitoring() {
        let child = Command::new("sleep")
            .arg("2")
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let started = Instant::now();
        assert!(read_child_limited(child, 128, Duration::from_millis(80))
            .unwrap()
            .is_none());
        assert!(started.elapsed() < Duration::from_millis(500));
    }

    #[test]
    fn large_image_payload_is_read_before_the_deadline() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("image.bin");
        std::fs::write(&path, vec![7; 1024 * 1024]).unwrap();
        let child = Command::new("cat")
            .arg(path)
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let bytes = read_child_limited(child, 1024 * 1024, Duration::from_secs(2))
            .unwrap()
            .unwrap();
        assert_eq!(bytes.len(), 1024 * 1024);
    }

    #[test]
    fn clipboard_writer_that_never_exits_does_not_block_copy() {
        let child = Command::new("sleep")
            .arg("2")
            .stdin(Stdio::piped())
            .spawn()
            .unwrap();
        let started = Instant::now();
        assert!(
            write_child_limited(child, b"file:///tmp/test\r\n", Duration::from_millis(80)).is_err()
        );
        assert!(started.elapsed() < Duration::from_millis(500));
    }
}
