use futures_util::StreamExt;
use std::sync::{atomic::Ordering, Arc};
use tauri::{AppHandle, Emitter, Manager};
use zbus::{fdo, message::Header};

const APP_BUS: &str = "dev.personalisland.Island";
const SHELL_BUS: &str = "org.gnome.Shell";
const PANEL_BUS: &str = "dev.personalisland.Shell";
const PATH: &str = "/dev/personalisland/Island";

pub async fn serve(app: AppHandle) {
    if let Err(error) = listen(app).await {
        eprintln!("GNOME Island integration: {error}");
    }
}

async fn listen(app: AppHandle) -> zbus::Result<()> {
    let connection = zbus::connection::Builder::session()?
        .name(APP_BUS)?
        .serve_at(PATH, Island(app.clone()))?
        .build()
        .await?;
    let bus = fdo::DBusProxy::new(&connection).await?;
    let mut changes = bus
        .receive_name_owner_changed_with_args(&[(0, PANEL_BUS)])
        .await?;
    while let Some(change) = changes.next().await {
        if change.args()?.new_owner().is_none() {
            app.state::<Arc<crate::clipboard::ClipboardState>>()
                .set_shell_monitor(false);
            set_height(&app, 0);
        }
    }
    Ok(())
}

struct Island(AppHandle);

#[zbus::interface(name = "dev.personalisland.Island")]
impl Island {
    async fn watch_clipboard(
        &self,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> fdo::Result<()> {
        verify_shell(&header, connection).await?;
        self.0
            .state::<Arc<crate::clipboard::ClipboardState>>()
            .set_shell_monitor(true);
        Ok(())
    }

    async fn clipboard_epoch(
        &self,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> fdo::Result<(bool, u32)> {
        verify_shell(&header, connection).await?;
        Ok(self
            .0
            .state::<Arc<crate::clipboard::ClipboardState>>()
            .shell_epoch())
    }

    async fn capture_clipboard(
        &self,
        epoch: u32,
        mime: String,
        data: Vec<u8>,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> fdo::Result<()> {
        verify_shell(&header, connection).await?;
        let state = self
            .0
            .state::<Arc<crate::clipboard::ClipboardState>>()
            .inner()
            .clone();
        let saved =
            tauri::async_runtime::spawn_blocking(move || state.capture_shell(epoch, &mime, data))
                .await
                .map_err(|error| fdo::Error::Failed(error.to_string()))?
                .map_err(fdo::Error::Failed)?;
        if saved {
            let _ = self.0.emit("clipboard-changed", ());
        }
        Ok(())
    }

    async fn attach(
        &self,
        height: u32,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> fdo::Result<()> {
        verify_shell(&header, connection).await?;
        set_height(&self.0, height.min(128));
        Ok(())
    }

    async fn toggle(
        &self,
        #[zbus(header)] header: Header<'_>,
        #[zbus(connection)] connection: &zbus::Connection,
    ) -> fdo::Result<()> {
        verify_shell(&header, connection).await?;
        crate::toggle_island_shortcut(self.0.clone()).map_err(fdo::Error::Failed)
    }
}

async fn verify_shell(header: &Header<'_>, connection: &zbus::Connection) -> fdo::Result<()> {
    let bus = fdo::DBusProxy::new(connection).await?;
    let owner = bus
        .get_name_owner(SHELL_BUS.try_into().map_err(zbus::Error::from)?)
        .await?;
    let panel = bus
        .get_name_owner(PANEL_BUS.try_into().map_err(zbus::Error::from)?)
        .await?;
    if header.sender() == Some(&owner) && panel == owner {
        return Ok(());
    }
    Err(fdo::Error::AccessDenied(
        "GNOME Island extension only".into(),
    ))
}

fn set_height(app: &AppHandle, height: u32) {
    let state = app.state::<crate::IslandPresentation>();
    let previous = state.panel_height.swap(height, Ordering::SeqCst);
    if previous == height || !state.ready.load(Ordering::SeqCst) {
        return;
    }
    // A native window request can wait for GTK. Keep the Shell bus free to
    // handle a clipboard notification while the surface is being attached.
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if handle
            .state::<crate::IslandPresentation>()
            .panel_height
            .load(Ordering::SeqCst)
            != height
        {
            return;
        }
        let _ = handle.emit("island-panel-height", height);
        if previous == 0 || height == 0 {
            let _ = crate::reveal_compact(&handle, "manual");
        }
    });
}
