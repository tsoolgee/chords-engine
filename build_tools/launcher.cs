// משגר: EXE יחיד שמכיל את כל התוכנה בתוכו (ZIP מוצמד לסוף הקובץ).
// בהפעלה ראשונה פורס אותה ל-%LOCALAPPDATA%\ChordsEngine\app\<גרסה>, ומשם מריץ. אחר כך — הפעלה מיידית.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Chords")]
[assembly: System.Reflection.AssemblyProduct("Chords")]

class SubStream : Stream {
    readonly Stream s; readonly long off, len; long pos;
    public SubStream(Stream s, long off, long len) { this.s = s; this.off = off; this.len = len; }
    public override bool CanRead { get { return true; } }
    public override bool CanSeek { get { return true; } }
    public override bool CanWrite { get { return false; } }
    public override long Length { get { return len; } }
    public override long Position { get { return pos; } set { pos = value; } }
    public override int Read(byte[] b, int o, int c) {
        if (pos >= len) return 0;
        if (c > len - pos) c = (int)(len - pos);
        s.Position = off + pos; int n = s.Read(b, o, c); pos += n; return n;
    }
    public override long Seek(long o, SeekOrigin k) {
        pos = k == SeekOrigin.Begin ? o : k == SeekOrigin.Current ? pos + o : len + o; return pos;
    }
    public override void Flush() { }
    public override void SetLength(long v) { throw new NotSupportedException(); }
    public override void Write(byte[] b, int o, int c) { throw new NotSupportedException(); }
}

static class Program {
    const string Magic = "CHRDPAK1";
    const string AppExe = "ChordsApp.exe";

    [STAThread]
    static int Main(string[] args) {
        string self = Application.ExecutablePath;
        long off, len; string ver;
        using (var fs = File.OpenRead(self)) {
            var t = new byte[48];
            fs.Seek(-48, SeekOrigin.End); fs.Read(t, 0, 48);
            if (Encoding.ASCII.GetString(t, 40, 8) != Magic) { MessageBox.Show("הקובץ פגום."); return 1; }
            off = BitConverter.ToInt64(t, 0); len = BitConverter.ToInt64(t, 8);
            ver = Encoding.ASCII.GetString(t, 16, 24).TrimEnd('\0', ' ');
        }
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ChordsEngine", "app");
        string dir = Path.Combine(root, ver);
        if (!File.Exists(Path.Combine(dir, ".complete"))) {
            Application.EnableVisualStyles();
            var f = new Form { Text = "אקורדים", Width = 460, Height = 150, FormBorderStyle = FormBorderStyle.FixedDialog,
                StartPosition = FormStartPosition.CenterScreen, MaximizeBox = false, MinimizeBox = false,
                RightToLeft = RightToLeft.Yes, RightToLeftLayout = true };
            var lbl = new Label { Text = "מכין את התוכנה להפעלה ראשונה (פעם אחת בלבד)…", Left = 16, Top = 16, Width = 410 };
            var bar = new ProgressBar { Left = 16, Top = 50, Width = 410, Height = 22, Maximum = 1000 };
            f.Controls.Add(lbl); f.Controls.Add(bar);
            Exception err = null;
            f.Shown += (s, e) => new Thread(() => {
                try { Extract(self, off, len, root, dir, p => f.BeginInvoke((Action)(() => bar.Value = Math.Min(1000, (int)(p * 1000))))); }
                catch (Exception ex) { err = ex; }
                f.BeginInvoke((Action)(() => f.Close()));
            }) { IsBackground = true }.Start();
            Application.Run(f);
            if (err != null) { MessageBox.Show("הפריסה נכשלה:\n" + err.Message, "אקורדים"); return 1; }
        }
        var psi = new ProcessStartInfo(Path.Combine(dir, AppExe)) { WorkingDirectory = dir, UseShellExecute = false };
        psi.Arguments = string.Join(" ", args.Select(a => "\"" + a + "\""));
        Process.Start(psi);
        return 0;
    }

    static void Extract(string self, long off, long len, string root, string dir, Action<double> progress) {
        string tmp = dir + ".tmp";
        if (Directory.Exists(tmp)) Directory.Delete(tmp, true);
        Directory.CreateDirectory(tmp);
        using (var fs = File.OpenRead(self))
        using (var zip = new ZipArchive(new SubStream(fs, off, len), ZipArchiveMode.Read)) {
            long total = zip.Entries.Sum(e => e.Length), done = 0;
            var buf = new byte[1 << 20];
            foreach (var e in zip.Entries) {
                string dst = Path.GetFullPath(Path.Combine(tmp, e.FullName));
                if (!dst.StartsWith(Path.GetFullPath(tmp))) continue;
                if (e.FullName.EndsWith("/")) { Directory.CreateDirectory(dst); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(dst));
                using (var i = e.Open()) using (var o = File.Create(dst)) {
                    int n; while ((n = i.Read(buf, 0, buf.Length)) > 0) { o.Write(buf, 0, n); done += n; progress(total > 0 ? (double)done / total : 1); }
                }
            }
        }
        if (Directory.Exists(dir)) Directory.Delete(dir, true);
        Directory.Move(tmp, dir);
        File.WriteAllText(Path.Combine(dir, ".complete"), DateTime.Now.ToString("o"));
        // גרסאות ישנות תופסות מקום — מוחקים (חוץ מזו שרצה עכשיו, אם נעולה)
        foreach (var old in Directory.GetDirectories(root))
            if (!string.Equals(old, dir, StringComparison.OrdinalIgnoreCase))
                try { Directory.Delete(old, true); } catch { }
    }
}
