param([Parameter(Mandatory=$true)][string]$Folder)
$ErrorActionPreference='Stop'
$null=[Windows.Media.Playback.MediaPlayer,Windows.Media.Playback,ContentType=WindowsRuntime]
$null=[Windows.Media.Core.MediaSource,Windows.Media.Core,ContentType=WindowsRuntime]
$null=[Windows.Media.Playback.MediaPlaybackItem,Windows.Media.Playback,ContentType=WindowsRuntime]
$player=New-Object Windows.Media.Playback.MediaPlayer
$player.Volume=0
$player.IsLoopingEnabled=$true
$source=[Windows.Media.Core.MediaSource]::CreateFromUri([Uri](Join-Path $Folder 'silence.wav'))
$item=New-Object Windows.Media.Playback.MediaPlaybackItem($source)
$controls=$player.SystemMediaTransportControls
$controls.IsEnabled=$true
$controls.IsPlayEnabled=$true
$controls.IsPauseEnabled=$true
$cover=$null
if(Test-Path -LiteralPath (Join-Path $Folder 'cover.png')) {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $null=[Windows.Storage.Streams.RandomAccessStreamReference,Windows.Storage.Streams,ContentType=WindowsRuntime]
  $null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
  $asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
  $fileTask=$asTask.MakeGenericMethod([Windows.Storage.StorageFile]).Invoke($null,@([Windows.Storage.StorageFile]::GetFileFromPathAsync((Join-Path $Folder 'cover.png'))))
  $file=$fileTask.GetAwaiter().GetResult()
  $cover=[Windows.Storage.Streams.RandomAccessStreamReference]::CreateFromFile($file)
}
$display=$item.GetDisplayProperties()
$display.Type=[Windows.Media.MediaPlaybackType]::Music
$display.MusicProperties.Title='QA Island Media Track'
$display.MusicProperties.Artist='QA Local Artist'
if($null -ne $cover) { $display.Thumbnail=$cover }
$item.ApplyDisplayProperties($display)
$player.Source=$item
$player.Play()
try {
  while(!(Test-Path -LiteralPath (Join-Path $Folder 'stop-media'))) {
    Start-Sleep -Milliseconds 400
  }
} finally { $player.Pause();$player.Dispose() }
