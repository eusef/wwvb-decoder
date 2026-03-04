using PortAudioSharp;
using System.Runtime.InteropServices;

namespace SDRconnectWebSocketAPI.AudioPlayer
{
    public class AudioPlayer
    {
        private readonly Fifo _fifo;
        private PortAudioSharp.Stream? _stream;

        private uint _framesPerBuffer;
        private bool _initialised;
        private bool _started;

        public AudioPlayer(uint framesPerBuffer)
        {
            _framesPerBuffer = framesPerBuffer;
            _fifo = new Fifo((int)_framesPerBuffer * 2);
        }

        public bool Start()
        {
            if (!_initialised)
            {
                PortAudio.Initialize();
                _initialised = true;
            }

            if (!_started)
            {
                _fifo.Reset();

                _started = true;
                if (!ConfigureAudio())
                {
                    return false;
                }
            }

            return true;
        }

        public void Stop()
        {
            if (_started)
            {
                _started = false;
                if(_stream != null)
                {
                    _stream.Stop();
                }

                if (_initialised)
                {
                    PortAudio.Terminate();
                    _initialised = false;
                }
            }
        }

        public void Write(short[] buffer)
        {
            if (_started)
            {
                _fifo.Write(buffer, buffer.Length);
            }
        }

        private bool ConfigureAudio()
        {
            var deviceIndex = PortAudio.DefaultOutputDevice;
            if (deviceIndex == PortAudio.NoDevice)
            {
                return false;
            }

            var info = PortAudio.GetDeviceInfo(deviceIndex);

            var param = new StreamParameters();
            param.device = deviceIndex;
            param.channelCount = 2;
            param.sampleFormat = SampleFormat.Int16;
            param.suggestedLatency = 0;
            param.hostApiSpecificStreamInfo = IntPtr.Zero;

            PortAudioSharp.Stream.Callback callback = (IntPtr input, IntPtr output,
                uint frameCount,
                ref StreamCallbackTimeInfo timeInfo,
                StreamCallbackFlags statusFlags,
                IntPtr userData) =>
            {
                if (_fifo.GetBuffer(out var buffer))
                {
                    Marshal.Copy(buffer, 0, output, (int)frameCount * 2);
                }

                return _started ? StreamCallbackResult.Continue : StreamCallbackResult.Abort;
            };

            _stream = new PortAudioSharp.Stream(inParams: null, outParams: param, sampleRate: 48000.0,
              framesPerBuffer: _framesPerBuffer,
              streamFlags: StreamFlags.NoFlag,
              callback: callback,
              userData: IntPtr.Zero);

            _stream.Start();

            return true;
        }
    }
}
