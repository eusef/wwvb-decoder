using SDRconnectWebSocketAPI.AudioPlayer;
using SDRconnectWebSocketAPI.Client;

class Program
{
    private static uint FramesPerBuffer = 4800;        
    private static SDRconnectWebSocketClient? _client;

    private static AudioPlayer? _audioPlayer;

    static void Main(string[] args)
    {
        _client = new SDRconnectWebSocketClient("127.0.0.1");
        _client.OnConnected += () => {         
            Console.WriteLine("Client connected");

            if (_client != null)
            {
                _client.DeviceStreamEnabled = true; 
                _client.AudioStreamEnabled = true;
            }
        };

        _client.OnAudioReceived += (short[] audio) => {
            if (_audioPlayer != null)
            {
                _audioPlayer.Write(audio);
            }
        };

        _audioPlayer = new AudioPlayer(FramesPerBuffer);
        if(!_audioPlayer.Start())
        {
            Console.WriteLine("Failed to initialise audio");
            return;
        }

        try
        {
            _client.Start();
        }
        catch
        {
            Console.WriteLine("Failed to connect");
            return;
        }

        Console.WriteLine("[Now Playing]");
        Console.WriteLine("Press enter to exit");
        Console.ReadLine();

        _audioPlayer.Stop();
        _client.Stop();
    }       
};