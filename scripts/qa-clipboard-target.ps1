param([Parameter(Mandatory=$true)][string]$Folder)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$backup=New-Object System.Windows.Forms.DataObject
$original=[System.Windows.Forms.Clipboard]::GetDataObject()
if($null -ne $original) {
  foreach($format in $original.GetFormats($false)) {
    try { $value=$original.GetData($format,$false); if($null -ne $value){$backup.SetData($format,$false,$value)} } catch {}
  }
}
$form=New-Object System.Windows.Forms.Form
$form.Text='Personal Island QA paste target'
$form.StartPosition='Manual'
$form.Location=New-Object System.Drawing.Point(80,210)
$form.Size=New-Object System.Drawing.Size(560,240)
$field=New-Object System.Windows.Forms.TextBox
$field.Multiline=$true
$field.Dock='Fill'
$field.Text='QA paste target'
$form.Controls.Add($field)
$field.Add_KeyDown({
  param($sender,$event)
  if($event.Control -and $event.KeyCode -eq 'V') {
    $event.SuppressKeyPress=$true
    if([System.Windows.Forms.Clipboard]::ContainsFileDropList()) {
      $paths=@([System.Windows.Forms.Clipboard]::GetFileDropList())
      @{kind='files';paths=$paths} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder 'pasted.json')
    } elseif([System.Windows.Forms.Clipboard]::ContainsImage()) {
      $picture=[System.Windows.Forms.Clipboard]::GetImage()
      @{kind='image';width=$picture.Width;height=$picture.Height} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder 'pasted.json')
      $picture.Dispose()
    } elseif([System.Windows.Forms.Clipboard]::ContainsText()) {
      $value=[System.Windows.Forms.Clipboard]::GetText()
      $field.Text=$value
      @{kind='text';text=$value} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder 'pasted.json')
    }
  }
})
$timer=New-Object System.Windows.Forms.Timer
$timer.Interval=100
$timer.Add_Tick({
  $commandPath=Join-Path $Folder 'command.json'
  if(Test-Path -LiteralPath $commandPath) {
    try {
      $command=Get-Content -Raw -Encoding utf8 -LiteralPath $commandPath | ConvertFrom-Json
      Remove-Item -LiteralPath $commandPath
      switch($command.action) {
        'text' { [System.Windows.Forms.Clipboard]::SetText($command.text) }
        'files' {
          $paths=New-Object System.Collections.Specialized.StringCollection
          foreach($path in $command.paths) { $null=$paths.Add($path) }
          [System.Windows.Forms.Clipboard]::SetFileDropList($paths)
        }
        'png-only' {
          $stream=New-Object System.IO.MemoryStream(,[System.IO.File]::ReadAllBytes($command.path))
          $data=New-Object System.Windows.Forms.DataObject
          $data.SetData('PNG',$false,$stream)
          [System.Windows.Forms.Clipboard]::SetDataObject($data,$true)
        }
        'image' {
          $picture=New-Object System.Drawing.Bitmap(80,60)
          $graphics=[System.Drawing.Graphics]::FromImage($picture)
          $graphics.Clear([System.Drawing.Color]::RoyalBlue)
          [System.Windows.Forms.Clipboard]::SetImage($picture)
          $graphics.Dispose();$picture.Dispose()
        }
        'focus' { $form.Activate();$field.Focus() }
        'clear-field' { $field.Clear();$form.Activate();$field.Focus() }
        'read-field' { @{text=$field.Text;focused=$field.Focused;active=$form.ContainsFocus} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder 'typed.json') }
        'stop' { $form.Close() }
      }
      @{id=$command.id} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Folder 'ack.json')
    } catch { $_.Exception.Message | Set-Content -Encoding utf8 (Join-Path $Folder 'target-error.txt') }
  }
})
$form.Add_Shown({$field.Focus();'ready' | Set-Content (Join-Path $Folder 'ready');$timer.Start()})
try { [System.Windows.Forms.Application]::Run($form) }
finally {
  $timer.Stop();$timer.Dispose()
  try { [System.Windows.Forms.Clipboard]::SetDataObject($backup,$true) } catch {}
  $form.Dispose()
}
