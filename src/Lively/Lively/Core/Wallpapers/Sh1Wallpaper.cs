using Lively.Common;
using Lively.Common.Extensions;
using Lively.Common.Helpers;
using Lively.Common.JsonConverters;
using Lively.Models;
using Lively.Models.Enums;
using Lively.Models.Message;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Lively.Core.Wallpapers
{
    /// <summary>
    /// The Silent Hill 1 fog-engine wallpaper player. Launches the bundled
    /// native player (plugins\sh1\Lively.Player.Sh1.exe — the GPL fog_poc
    /// engine with the LIVELY_PLAYER seam) as a child process and follows
    /// the same IPC contract as WebWebView2/ExtPrograms:
    /// stdout JSON lines (msg_hwnd -> the player window handle we parent to
    /// the WorkerW, msg_wploaded -> the first presented frame),
    /// stdin JSON commands (pause/resume/close + the LivelyProperties
    /// lp_dropdown/lp_chekbox changes, applied LIVE by the engine).
    /// </summary>
    public class Sh1Wallpaper : IWallpaper
    {
        private static readonly NLog.Logger Logger = NLog.LogManager.GetCurrentClassLogger();
        private readonly TaskCompletionSource<Exception> tcsProcessWait = new();
        private readonly TaskCompletionSource contentReadyTcs = new();
        private bool IsContentReady => contentReadyTcs.Task.IsCompleted;
        private readonly Process process;
        private static int globalCount;
        private readonly int uniqueId;
        private bool isInitialized;

        public event EventHandler Exited;
        public event EventHandler Loaded;

        public bool IsLoaded { get; private set; } = false;

        public WallpaperType Category => Model.LivelyInfo.Type;

        public LibraryModel Model { get; }

        public IntPtr Handle { get; private set; }

        public IntPtr InputHandle => Handle;

        public int? Pid { get; private set; } = null;

        public DisplayMonitor Screen { get; set; }

        public string LivelyPropertyCopyPath { get; }

        public bool IsExited { get; private set; }

        public Sh1Wallpaper(string path,
            LibraryModel model,
            DisplayMonitor display,
            string livelyPropertyPath,
            string arguments = null)
        {
            LivelyPropertyCopyPath = livelyPropertyPath;

            var cmdArgs = new StringBuilder();
            // the wallpaper folder = the LivelyInfo.json dir (the bundle
            // layout: sh1\<SCENE>.glb + sh1\camdat.json inside it).
            string wallpaperDir = Path.GetDirectoryName(path);
            cmdArgs.Append(" --wallpaper-path \"");
            cmdArgs.Append(wallpaperDir);
            cmdArgs.Append("\"");
            if (!string.IsNullOrEmpty(arguments))
            {
                cmdArgs.Append(' ');
                cmdArgs.Append(arguments);
            }
            // the LivelyInfo.json FileName is the exe itself; the scene
            // etc. live beside it in the wallpaper folder.
            if (!string.IsNullOrEmpty(livelyPropertyPath))
            {
                cmdArgs.Append(" --wallpaper-property \"");
                cmdArgs.Append(livelyPropertyPath);
                cmdArgs.Append("\"");
            }

            process = new Process
            {
                EnableRaisingEvents = true,   /* audit B-D1: Exited fires only with this */
                StartInfo = new ProcessStartInfo
                {
                    Arguments = cmdArgs.ToString(),
                    FileName = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, Constants.PlayerPartialPaths.Sh1Path),
                    RedirectStandardInput = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,   /* S18 audit D2: the player's fatal
                                                      * diagnostics (fprintf stderr: 'cannot
                                                      * find THRF9FD.glb' etc.) were invisible —
                                                      * the user's log had only 'exit code: 1' */
                    UseShellExecute = false,
                    StandardInputEncoding = Encoding.UTF8,
                    WorkingDirectory = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, Constants.PlayerPartialPaths.Sh1Dir)
                },
            };
            this.Model = model;
            this.Screen = display;

            //for logging purpose
            uniqueId = globalCount++;
        }

        public void Close()
        {
            if (IsExited)
                return;

            SendMessage(new LivelyCloseCmd());
        }

        public void Pause()
        {
            if (!IsContentReady)
                return;

            SendMessage(new LivelySuspendCmd()); //"{\"Type\":7}"
        }

        public void Play()
        {
            if (!IsContentReady)
                return;

            SendMessage(new LivelyResumeCmd()); //"{\"Type\":8}"
        }

        private void SendMessage(string msg)
        {
            if (IsExited)
                return;

            try
            {
                process?.StandardInput.WriteLine(msg);
                process?.StandardInput.Flush();
            }
            catch (Exception e)
            {
                Logger.Error($"Sh1{uniqueId}: Stdin write fail: {e.Message}");
            }
        }

        public void SendMessage(IpcMessage obj)
        {
            if (IsExited)
                return;

            SendMessage(JsonConvert.SerializeObject(obj));
        }

        public void SetVolume(int volume)
        {
            // silent engine — accepted for contract parity, no-op.
        }

        public void SetMute(bool mute)
        {
            // silent engine — no-op.
        }

        public async Task ShowAsync()
        {
            if (process is null)
                return;

            try
            {
                process.Exited += Proc_Exited;
                process.OutputDataReceived += Proc_OutputDataReceived;
                process.ErrorDataReceived += Proc_ErrorDataReceived;   /* S18 audit D2 */
                process.Start();
                Pid = process.Id;
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();

                await tcsProcessWait.Task;
                if (tcsProcessWait.Task.Result is not null)
                    throw tcsProcessWait.Task.Result;
            }
            catch (Exception)
            {
                Terminate();

                throw;
            }
        }

        /* S18 audit D2: the player's stderr (engine boot errors, e.g.
         * "cannot find THRF9FD.glb") is now captured into the app log so a
         * startup failure carries its reason instead of a bare exit code. */
        private void Proc_ErrorDataReceived(object sender, DataReceivedEventArgs e)
        {
            if (string.IsNullOrEmpty(e.Data))
                return;
            Logger.Info($"Sh1{uniqueId}: {e.Data}");
        }

        private void Proc_Exited(object sender, EventArgs e)
        {
            Logger.Info($"Sh1{uniqueId}: Process exited with exit code: {process?.ExitCode}");            if (!isInitialized)
            {
                //startup failed: msg_hwnd never arrived.
                tcsProcessWait.TrySetResult(
                    new InvalidOperationException($"Sh1 player exited before showing window."));
            }
            IsExited = true;
            contentReadyTcs.TrySetResult();
            try { process?.Dispose(); } catch { }   /* audit B-D3 */
            Exited?.Invoke(this, EventArgs.Empty);
        }

        private async void Proc_OutputDataReceived(object sender, DataReceivedEventArgs e)
        {
            try
            {
                if (string.IsNullOrEmpty(e.Data))
                    return;

                if (!e.Data.TrimStart().StartsWith("{"))
                {
                    Logger.Info($"Sh1{uniqueId}: {e.Data}");
                    return;
                }

                var obj = JsonConvert.DeserializeObject<IpcMessage>(e.Data, new JsonSerializerSettings() { Converters = { new IpcMessageConverter() } });
                if (obj is null)
                    return;

                switch (obj.Type)
                {
                    case MessageType.msg_hwnd:
                        if (!isInitialized)
                        {
                            Exception error = null;
                            try
                            {
                                Handle = new IntPtr(((LivelyMessageHwnd)obj).Hwnd);
                                if (IntPtr.Equals(Handle, IntPtr.Zero))
                                    throw new Exception("Player window handle NULL.");
                            }
                            catch (Exception ie)
                            {
                                error = ie;
                            }
                            finally
                            {
                                isInitialized = true;
                                tcsProcessWait.TrySetResult(error);
                            }
                        }
                        break;
                    case MessageType.msg_wploaded:
                        if (!IsLoaded)
                        {
                            var loaded = (LivelyMessageWallpaperLoaded)obj;
                            if (!loaded.Success)
                            {
                                Logger.Error($"Sh1{uniqueId}: Player reported load failure.");
                            }
                            IsLoaded = true;
                            Loaded?.Invoke(this, EventArgs.Empty);

                            await Task.Delay(1000);
                            if (!IsExited)
                                contentReadyTcs.TrySetResult();
                            else
                                contentReadyTcs.TrySetException(new InvalidOperationException("Process exited."));
                        }
                        break;
                    case MessageType.msg_console:
                        var c = (LivelyMessageConsole)obj;
                        if (c.Category == ConsoleMessageType.error)
                            Logger.Error($"Sh1{uniqueId}: {c.Message}");
                        else
                            Logger.Info($"Sh1{uniqueId}: {c.Message}");
                        break;
                }
            }
            catch (Exception ex)
            {
                Logger.Error($"Sh1{uniqueId}: Stdout parse error: {ex.Message}");
            }
        }

        public void Terminate()
        {
            if (IsExited)
                return;

            try
            {
                process.Kill();
            }
            catch { }
        }

        public void SetPlaybackPos(float pos, PlaybackPosType type)
        {
            // The engine plays its own authored camera track; no seek API.
        }

        public Task ScreenCapture(string filePath)
        {
            /* audit B-D2: the desktop-auto-wallpaper path calls this on
             * load; a throw logs errors on every wallpaper change. The
             * native player has no screenshot IPC yet (follow-up: a
             * msg_screenshot round-trip like WebWebView2). */
            return Task.CompletedTask;
        }

        public void Dispose()
        {
            Terminate();   /* audit B-D3: Dispose must kill a hung player */
            process?.Dispose();
            GC.SuppressFinalize(this);
        }
    }
}
