//! Windows file-drop and PNG formats, in addition to arboard's text/DIB support.
use windows::{
    core::w,
    Win32::{
        Foundation::{GlobalFree, HANDLE, HGLOBAL, HWND},
        System::{DataExchange::*, Memory::*},
        UI::Shell::{DragQueryFileW, HDROP},
    },
};
pub const FILE_DROP: u32 = 15;
pub const MAX_FILES: usize = 64;
struct Clipboard;
impl Clipboard {
    fn open(owner: Option<HWND>) -> Result<Self, String> {
        unsafe { OpenClipboard(owner) }.map_err(|e| e.to_string())?;
        Ok(Self)
    }
}
impl Drop for Clipboard {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseClipboard();
        }
    }
}
pub fn read_files() -> Result<Option<Vec<String>>, String> {
    unsafe {
        if IsClipboardFormatAvailable(FILE_DROP).is_err() {
            return Ok(None);
        }
        let _clipboard = Clipboard::open(None)?;
        let drop = HDROP(GetClipboardData(FILE_DROP).map_err(|e| e.to_string())?.0);
        let count = DragQueryFileW(drop, u32::MAX, None);
        // An oversized file set is handled but not collected as fallback text.
        if count as usize > MAX_FILES {
            return Ok(Some(Vec::new()));
        }
        let mut paths = Vec::new();
        for index in 0..count {
            let length = DragQueryFileW(drop, index, None);
            if length == 0 || length > 32767 {
                return Ok(Some(Vec::new()));
            }
            let mut path = vec![0u16; length as usize + 1];
            if DragQueryFileW(drop, index, Some(&mut path)) != length {
                return Err("Список файлов изменился".into());
            }
            paths.push(String::from_utf16(&path[..length as usize]).map_err(|e| e.to_string())?);
        }
        Ok(Some(paths))
    }
}
pub fn read_png() -> Result<Option<Vec<u8>>, String> {
    unsafe {
        let format = [
            RegisterClipboardFormatW(w!("PNG")),
            RegisterClipboardFormatW(w!("image/png")),
        ]
        .into_iter()
        .find(|format| IsClipboardFormatAvailable(*format).is_ok());
        let Some(format) = format else {
            return Ok(None);
        };
        let _clipboard = Clipboard::open(None)?;
        let memory = HGLOBAL(GetClipboardData(format).map_err(|e| e.to_string())?.0);
        let length = GlobalSize(memory);
        if length == 0 || length > 8 * 1024 * 1024 {
            return Ok(None);
        }
        let pointer = GlobalLock(memory);
        if pointer.is_null() {
            return Err("Картинка временно недоступна".into());
        }
        let bytes = std::slice::from_raw_parts(pointer as *const u8, length).to_vec();
        let _ = GlobalUnlock(memory);
        Ok(Some(bytes))
    }
}
fn drop_bytes(paths: &[String]) -> Result<Vec<u8>, String> {
    if paths.is_empty() || paths.len() > MAX_FILES {
        return Err("Можно скопировать от 1 до 64 файлов".into());
    }
    let mut bytes = vec![0u8; 20]; // DROPFILES: offset, POINT, nonclient flag, UTF-16 flag.
    bytes[..4].copy_from_slice(&20u32.to_le_bytes());
    bytes[16..20].copy_from_slice(&1u32.to_le_bytes());
    for path in paths {
        if !std::path::Path::new(path).is_absolute() || path.contains('\0') {
            return Err("Неверный путь файла".into());
        }
        for unit in path.encode_utf16().chain(std::iter::once(0)) {
            bytes.extend_from_slice(&unit.to_le_bytes());
        }
    }
    bytes.extend_from_slice(&[0, 0]);
    if bytes.len() > 256 * 1024 {
        return Err("Слишком длинный список файлов".into());
    }
    Ok(bytes)
}
struct Block(HGLOBAL);
impl Block {
    fn new(bytes: &[u8]) -> Result<Self, String> {
        unsafe {
            let memory = Self(GlobalAlloc(GMEM_MOVEABLE, bytes.len()).map_err(|e| e.to_string())?);
            let pointer = GlobalLock(memory.0);
            if pointer.is_null() {
                return Err("Не удалось выделить память буфера".into());
            }
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), pointer as *mut u8, bytes.len());
            let _ = GlobalUnlock(memory.0);
            Ok(memory)
        }
    }
    unsafe fn transfer(&mut self, format: u32) -> Result<(), String> {
        SetClipboardData(format, Some(HANDLE(self.0 .0))).map_err(|e| e.to_string())?;
        self.0 = HGLOBAL::default(); // Ownership belongs to Windows after success.
        Ok(())
    }
}
impl Drop for Block {
    fn drop(&mut self) {
        if !self.0 .0.is_null() {
            unsafe {
                let _ = GlobalFree(Some(self.0));
            }
        }
    }
}
pub fn write_files(owner: isize, paths: &[String]) -> Result<(), String> {
    let bytes = drop_bytes(paths)?;
    for path in paths {
        if !std::path::Path::new(path).try_exists().unwrap_or(false) {
            return Err(format!("Файл перемещён или удалён: {path}"));
        }
    }
    let mut files = Block::new(&bytes)?;
    // Always copy. Reusing a historical Cut must never move/delete its source.
    let mut effect = Block::new(&1u32.to_le_bytes())?;
    unsafe {
        let _clipboard = Clipboard::open(Some(HWND(owner as *mut _)))?;
        EmptyClipboard().map_err(|e| e.to_string())?;
        files.transfer(FILE_DROP)?;
        effect.transfer(RegisterClipboardFormatW(w!("Preferred DropEffect")))?;
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn file_drop_contains_exact_unicode_paths_and_double_terminator() {
        let paths = vec![
            r"C:\Фото\Петербург 🌊.png".into(),
            r"C:\Документы\план.pdf".into(),
        ];
        let data = drop_bytes(&paths).unwrap();
        assert_eq!(&data[..4], &20u32.to_le_bytes());
        assert_eq!(&data[16..20], &1u32.to_le_bytes());
        let text: Vec<u16> = data[20..]
            .chunks_exact(2)
            .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
            .collect();
        assert_eq!(
            String::from_utf16(&text).unwrap(),
            format!("{}\0{}\0\0", paths[0], paths[1])
        );
        assert!(drop_bytes(&["relative.txt".into()]).is_err());
        assert!(drop_bytes(&[]).is_err());
    }
}
