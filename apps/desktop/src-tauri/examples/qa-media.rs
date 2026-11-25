//! Silent, local test player with three real system-controllable tracks.
#[cfg(windows)]
use windows::{
    core::HSTRING,
    Foundation::{TypedEventHandler, Uri},
    Media::{
        Core::MediaSource,
        MediaPlaybackType,
        Playback::{MediaPlaybackItem, MediaPlaybackList, MediaPlayer},
        PlaybackPositionChangeRequestedEventArgs, SystemMediaTransportControls,
    },
    Storage::{StorageFile, Streams::RandomAccessStreamReference},
    Win32::System::WinRT::{RoInitialize, RO_INIT_MULTITHREADED},
};
#[cfg(windows)]
fn main() -> windows::core::Result<()> {
    unsafe {
        RoInitialize(RO_INIT_MULTITHREADED)?;
    }
    let folder = std::path::PathBuf::from(std::env::args().nth(1).expect("fixture folder"));
    if let Ok(identity) = std::env::var("PERSONAL_ISLAND_QA_MEDIA_ID") {
        unsafe {
            windows::Win32::UI::Shell::SetCurrentProcessExplicitAppUserModelID(&HSTRING::from(
                format!("qa-media.{identity}"),
            ))?;
        }
    }
    let cover = StorageFile::GetFileFromPathAsync(&HSTRING::from(
        folder.join("cover.png").to_string_lossy().as_ref(),
    ))?
    .join()?;
    let thumbnail = RandomAccessStreamReference::CreateFromFile(&cover)?;
    let player = MediaPlayer::new()?;
    player.SetVolume(0.0)?;
    let list = MediaPlaybackList::new()?;
    list.SetAutoRepeatEnabled(true)?;
    for index in 1..=3 {
        let uri = Uri::CreateUri(&HSTRING::from(
            folder.join("silence.wav").to_string_lossy().as_ref(),
        ))?;
        let item = MediaPlaybackItem::Create(&MediaSource::CreateFromUri(&uri)?)?;
        let display = item.GetDisplayProperties()?;
        display.SetType(MediaPlaybackType::Music)?;
        display
            .MusicProperties()?
            .SetTitle(&HSTRING::from(format!("QA Track {index}")))?;
        display
            .MusicProperties()?
            .SetArtist(&HSTRING::from("QA Local Artist"))?;
        display.SetThumbnail(&thumbnail)?;
        item.ApplyDisplayProperties(&display)?;
        list.Items()?.Append(&item)?;
    }
    player.SetSource(&list)?;
    let controls = player.SystemMediaTransportControls()?;
    controls.SetIsEnabled(true)?;
    controls.SetIsNextEnabled(true)?;
    controls.SetIsPreviousEnabled(true)?;
    let playback = player.PlaybackSession()?;
    let diagnostic = folder.join("seek-received.txt");
    let seek_handler = TypedEventHandler::<
        SystemMediaTransportControls,
        PlaybackPositionChangeRequestedEventArgs,
    >::new(move |_, args| {
        if let Some(args) = args.as_ref() {
            let _ = std::fs::write(
                &diagnostic,
                args.RequestedPlaybackPosition()?.Duration.to_string(),
            );
            playback.SetPosition(args.RequestedPlaybackPosition()?)?;
        }
        Ok(())
    });
    let _seek_token = controls.PlaybackPositionChangeRequested(&seek_handler)?;
    player.Play()?;
    while !folder.join("stop-media").exists() {
        if let Ok(position) = player
            .PlaybackSession()
            .and_then(|session| session.Position())
        {
            let _ = std::fs::write(
                folder.join("media-position.txt"),
                position.Duration.to_string(),
            );
        }
        if folder.join("pause-media").exists() {
            let _ = std::fs::remove_file(folder.join("pause-media"));
            player.Pause()?;
        }
        if folder.join("resume-media").exists() {
            let _ = std::fs::remove_file(folder.join("resume-media"));
            player.Play()?;
        }
        if folder.join("mute-session").exists() {
            let _ = std::fs::remove_file(folder.join("mute-session"));
            mute_audio_session()?;
            std::fs::write(folder.join("muted-session"), b"ready").unwrap();
        }
        if folder.join("next-media").exists() {
            let _ = std::fs::remove_file(folder.join("next-media"));
            list.MoveNext()?;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    player.Pause()?;
    player.Close()?;
    Ok(())
}

#[cfg(not(windows))]
fn main() {
    eprintln!("qa-media is a Windows-only QA fixture");
}

#[cfg(windows)]
fn mute_audio_session() -> windows::core::Result<()> {
    use windows::{
        core::Interface,
        Win32::{
            Media::Audio::*,
            System::{Com::*, Threading::GetCurrentProcessId},
        },
    };
    unsafe {
        let devices: IMMDeviceEnumerator = CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)?;
        let endpoints = devices.EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE)?;
        let mut found = false;
        for index in 0..endpoints.GetCount()? {
            let endpoint = endpoints.Item(index)?;
            let manager = endpoint.Activate::<IAudioSessionManager2>(CLSCTX_ALL, None)?;
            let sessions = manager.GetSessionEnumerator()?;
            for index in 0..sessions.GetCount()? {
                let session = sessions.GetSession(index)?;
                if session.cast::<IAudioSessionControl2>()?.GetProcessId()? == GetCurrentProcessId()
                {
                    session
                        .cast::<ISimpleAudioVolume>()?
                        .SetMute(true, std::ptr::null())?;
                    found = true;
                }
            }
        }
        assert!(found, "Silent fixture has no Core Audio session");
    }
    Ok(())
}
