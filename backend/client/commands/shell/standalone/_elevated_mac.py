"""macOS authorization for tracked commands and direct output collection."""

import base64
from contextlib import contextmanager
import shlex
import subprocess
import tempfile

from client.commands.platform.utils.mac_util import escape_osascript_text
from client.commands.shell.standalone._elevated_process import ElevationCancelled, run_tracked


# Perl is already used by the macOS Client launcher for setsid(2). Use a
# close-on-exec pipe to distinguish a successful exec from a launch failure,
# including a target which succeeds and then exits before its PID is reported.
_MAC_HELPER = r'''
use strict;
use warnings;
use Fcntl qw(F_SETFD FD_CLOEXEC);
use IO::Select;
use IO::Socket::INET;
use JSON::PP qw(decode_json);
use MIME::Base64 qw(decode_base64);
use POSIX qw(setsid WNOHANG _exit);

my $r = decode_json(decode_base64($ARGV[0]));
my $link = IO::Socket::INET->new(PeerAddr => '127.0.0.1', PeerPort => $r->{port},
                                 Proto => 'tcp', Timeout => 5) or die "RCH connection: $!";
$link->autoflush(1);
$SIG{PIPE} = 'IGNORE';
sub packet {
    my ($kind, $data) = @_;
    print {$link} pack('aN', $kind, length($data)), $data or die "RCH connection closed";
}
packet('T', $r->{token});
exit 1 unless IO::Select->new($link)->can_read(5);
my $ack;
exit 1 unless read($link, $ack, length($r->{ack})) && $ack eq $r->{ack};

my $detached = $r->{mode} eq 'detached';
my @args = $detached ? @{$r->{command}} : ('/bin/sh', '-c', $r->{command});
utf8::encode($_) for grep { utf8::is_utf8($_) } @args;
my $cwd = $r->{cwd};
utf8::encode($cwd) if utf8::is_utf8($cwd);
pipe(my $status, my $report) or die "launch status pipe: $!";
fcntl($report, F_SETFD, FD_CLOEXEC) or die "close-on-exec: $!";
pipe(my $output, my $writer) or die "output pipe: $!";
my $pid = fork();
if (!defined $pid) {
    packet('E', "Cannot create process: $!");
    exit 1;
}
if ($pid == 0) {
    close $status;
    close $output;
    close $link;
    eval {
        setsid() >= 0 or die "setsid: $!";
        chdir($cwd) or die "Working directory: $!";
        open(STDIN, '<', '/dev/null') or die "stdin: $!";
        if ($detached) {
            open(STDOUT, '>', '/dev/null') or die "stdout: $!";
        } else {
            open(STDOUT, '>&', $writer) or die "stdout: $!";
        }
        close $writer;
        open(STDERR, '>&', \*STDOUT) or die "stderr: $!";
        $SIG{PIPE} = 'DEFAULT';
        exec { $args[0] } @args or die "Cannot start $args[0]: $!";
    };
    syswrite($report, $@);
    _exit(127);
}
close $report;
close $writer;
my $failure;
if (sysread($status, $failure, 8192)) {
    waitpid($pid, 0);
    packet('E', $failure);
    exit 1;
}
close $status;
if ($detached) {
    waitpid($pid, WNOHANG);
    packet('P', "$pid");
    exit 0;
}

my $select = IO::Select->new($link, $output);
my $exit_code;
eval {
    while (1) {
        if (!defined($exit_code) && waitpid($pid, WNOHANG) == $pid) {
            $exit_code = ($? & 127) ? 128 + ($? & 127) : $? >> 8;
        }
        my @ready = $select->can_read(defined($exit_code) ? 0 : 0.05);
        last if defined($exit_code) && !@ready;
        for my $handle (@ready) {
            die "RCH connection closed" if $handle == $link;
            if (sysread($output, my $data, 8192)) {
                packet('O', $data);
            } else {
                $select->remove($output);
            }
        }
    }
    packet('X', "$exit_code");
};
if (!defined($exit_code)) {
    kill 'KILL', -$pid;
    waitpid($pid, 0);
}
'''


@contextmanager
def _launch_helper(payload, _cwd):
    # Keep diagnostics separate from the socket while osascript is waiting
    # for authorization. TemporaryFile also avoids waiting on a stderr pipe.
    helper = base64.b64encode(_MAC_HELPER.encode('ascii')).decode('ascii')
    source = shlex.join([
        '/usr/bin/perl', '-MMIME::Base64', '-e', 'eval decode_base64(shift @ARGV); die $@ if $@;',
        '--', helper, payload,
    ])
    script = f'do shell script "{escape_osascript_text(source)}" with administrator privileges'
    with tempfile.TemporaryFile() as diagnostics:
        process = subprocess.Popen(['/usr/bin/osascript', '-e', script], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=diagnostics)

        def error_if_exited():
            code = process.poll()
            if code is not None:
                diagnostics.seek(0)
                detail = diagnostics.read(8192).decode('utf-8', errors='replace').strip()
                if '(-128)' in detail:
                    raise ElevationCancelled('macOS authorization cancelled')
                raise OSError(detail or f'osascript exited before starting the elevated helper ({code})')

        try:
            yield error_if_exited
        finally:
            if process.poll() is None:
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


class MacElevation:
    def __init__(self, owner):
        self.owner = owner

    def shell(self, command):
        return run_tracked(self.owner, _launch_helper, 'shell', command)

    def collect(self, command):
        script = f'do shell script "{escape_osascript_text(command)}" with administrator privileges'
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return 1, result.stdout
        if '(-128)' in result.stderr:
            raise ElevationCancelled('macOS authorization cancelled')
        return 0, result.stderr

    def detached(self, argv):
        return run_tracked(self.owner, _launch_helper, 'detached', argv)
