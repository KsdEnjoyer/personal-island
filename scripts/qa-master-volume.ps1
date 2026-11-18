# Read-only test probe. Production uses only ISimpleAudioVolume (session gain).
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class MasterProbe {
 [ComImport,Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class Enumerator {}
 [ComImport,Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IEnum {
  void EnumAudioEndpoints(int flow,int mask,out object devices);
  void GetDefaultAudioEndpoint(int flow,int role,out IDevice device);
 }
 [ComImport,Guid("D666063F-1587-4E43-81F1-B948E807363F"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IDevice {
  void Activate(ref Guid iid,int context,IntPtr parameters,[MarshalAs(UnmanagedType.IUnknown)]out object obj);
 }
 [ComImport,Guid("5CDF2C82-841E-4546-9722-0CF74078229A"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] interface IVolume {
  void RegisterControlChangeNotify(IntPtr notify); void UnregisterControlChangeNotify(IntPtr notify);
  void GetChannelCount(out uint count); void SetMasterVolumeLevel(float level,IntPtr context);
  void SetMasterVolumeLevelScalar(float level,IntPtr context); void GetMasterVolumeLevel(out float level);
  void GetMasterVolumeLevelScalar(out float level);
 }
 public static float Read() {
  var e=(IEnum)new Enumerator(); IDevice device; e.GetDefaultAudioEndpoint(0,1,out device);
  var iid=typeof(IVolume).GUID; object volume; device.Activate(ref iid,23,IntPtr.Zero,out volume);
  float value; ((IVolume)volume).GetMasterVolumeLevelScalar(out value);
  Marshal.ReleaseComObject(volume); Marshal.ReleaseComObject(device); Marshal.ReleaseComObject(e); return value;
 }
}
'@
[MasterProbe]::Read().ToString([System.Globalization.CultureInfo]::InvariantCulture)
