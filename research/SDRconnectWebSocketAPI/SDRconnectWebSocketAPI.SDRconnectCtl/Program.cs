using SDRconnectWebSocketAPI.Client;

class Program
{
    private static bool _verbose = false;

    private static void ShowUsage()
    {
        Console.WriteLine("Example command line utility for controlling SDRconnect");
        Console.WriteLine();
        Console.WriteLine("[--set_vfo_freq=<value>] [--set_device_center_freq=<value>]");
        Console.WriteLine("[--set_demodulator=<mode>] [--set_filter_bandwdith=<value>]");        
        Console.WriteLine("[--verbose=<true|false>] [--host=<ip address> default: 127.0.0.1]");
        Console.WriteLine("[--set_device_stream=<true|false>] [--set_device=<index>]");
        Console.WriteLine("[--start_recording=<iq|audio|compressed_audio>] [--stop_recording=<true>]");
        Console.WriteLine("[--apply_device_profile=<profile name>] [--help]");
    }

    private static void ParserFailure(string message)
    {
        Console.WriteLine("Invalid argument: {0}", message);
    }

    private static bool HandleSetVfoFrequency(string[] parts, SDRconnectWebSocketClient client)
    {
        ulong val = 0;

        if (!ulong.TryParse(parts[1], out val))
        {
            ParserFailure("set_vfo_freq: expected frequency value");
            return false;
        }

        if (_verbose)
        {
            Console.WriteLine("[set_vfo_freq = {0}]", val);
        }

        client.SetProperty(SDRconnectProperty.device_vfo_frequency, val.ToString());
        return true;
    }

    private static bool HandleSetDeviceCenterFrequency(string[] parts, SDRconnectWebSocketClient client)
    {
        if (!ulong.TryParse(parts[1], out var val))
        {
            ParserFailure("set_device_center_freq: expected frequency value");
            return false;
        }

        if (_verbose)
        {
            Console.WriteLine("[set_device_center_freq = {0}]", val);
        }

        client.SetProperty(SDRconnectProperty.device_center_frequency, val.ToString());
        return true;
    }

    private static bool HandleSetVfoMode(string[] parts, SDRconnectWebSocketClient client)
    {
        if (_verbose)
        {
            Console.WriteLine("[set_demodulator = {0}]", parts[1].ToUpper());
        }

        client.SetProperty(SDRconnectProperty.demodulator, parts[1].ToUpper());
        return true;
    }

    private static bool HandleSetDeviceStreamEnable(string[] parts, SDRconnectWebSocketClient client)
    {
        var s = parts[1].ToLower();
        if (s != "true" && s != "false")
        {
            ParserFailure("set_device_stream: expected boolean");
            return false;
        }

        if (_verbose)
        {
            Console.WriteLine("[set_device_stream = {0}]", s);
        }

        client.DeviceStreamEnabled = s == "true" ? true : false;
        return true;
    }

    private static bool HandleSetFilterBandwidth(string[] parts, SDRconnectWebSocketClient client)
    {
        if (uint.TryParse(parts[1], out var bandwidth))
        {
            ParserFailure("set_filter_bandwidth: expected filter bandwidth");
            return false;
        }

        if (_verbose)
        {
            Console.WriteLine("[set_filter_bandwidth = {0}]", bandwidth);
        }

        client.SetProperty(SDRconnectProperty.filter_bandwidth, bandwidth.ToString());
        return true;
    }

    private static bool HandleSetDevice(string[] parts, SDRconnectWebSocketClient client)
    {
        if (!int.TryParse(parts[1], out var deviceIndex))
        {
            ParserFailure("set_device: expected device index");
            return false;
        }

        if (_verbose)
        {
            Console.WriteLine("[set_device {0}]", deviceIndex);
        }

        client.SetCurrentDevice(deviceIndex);
        return true;
    }

    private static bool HandleStartRecording(string[] parts, SDRconnectWebSocketClient client)
    {
        var s = parts[1].ToLower();
        if (s != "iq" && s != "audio" && s != "compressed_audio")
        {
            ParserFailure("start_recording: expected recording type (iq, audio, compressed_audio");
            return false;
        }

        if(_verbose)
        {
            Console.WriteLine("[start_recording={0}", s);
        }

        var type = (SDRconnectRecording.RecordingType) Enum.Parse(typeof(SDRconnectRecording.RecordingType), s);
        client.StartRecording(type);
        return true;
    }

    private static bool HandleStopRecording(string[] parts, SDRconnectWebSocketClient client)
    {
        var s = parts[1].ToLower();
        if(s != "true")
        {
            ParserFailure("stop_recording: expected true");
            return false;
        }

        if (_verbose)
        {
            Console.WriteLine("[stop_recording]");
        }

        client.StopRecording();
        return true;
    }

    private static bool HandleApplyDeviceProfile(string[] parts, SDRconnectWebSocketClient client)
    {
        var s = parts[1];
        
        if (_verbose)
        {
            Console.WriteLine("[apply_device_profile={0}]", s);
        }

        client.ApplyDeviceProfile(s);
        return true;
    }

    private static bool ParseArguments(string[] args, SDRconnectWebSocketClient client)
    {
        for (var i = 0; i < args.Length; i++)
        {
            var parts = args[i].Split('=');
            if (parts.Length != 2)
            {
                ParserFailure("Unexpected argument");
                return false;
            }

            if (!parts[0].StartsWith("--"))
            {
                ParserFailure("Unexpected argument");
                return false;
            }

            parts[0] = parts[0].Replace("--", null);

            switch (parts[0])
            {
                case "set_vfo_freq":
                    if(!HandleSetVfoFrequency(parts, client))
                    {
                        return false;
                    }
                    break;

                case "set_vfo_mode":
                    if(!HandleSetVfoMode(parts, client))
                    {
                        return false;
                    }
                    break;

                case "set_device_center_freq":
                    if(!HandleSetDeviceCenterFrequency(parts, client))
                    {
                        return false;
                    }
                    break;

                case "set_device_stream":
                    if(!HandleSetDeviceStreamEnable(parts, client))
                    {
                        return false;
                    }
                    break;

                case "set_filter_bandwidth":
                    if(!HandleSetFilterBandwidth(parts, client))
                    {
                        return false;
                    }
                    break;

                case "set_device":
                    if(!HandleSetDevice(parts, client))
                    {
                        return false;
                    }
                    break;

                case "start_recording":
                    if(!HandleStartRecording(parts, client))
                    {
                        return false;
                    }    
                    break;

                case "stop_recording":
                    if(!HandleStopRecording(parts, client))
                    {
                        return false;
                    }
                    break;

                case "apply_device_profile":
                    if(!HandleApplyDeviceProfile(parts, client))
                    {
                        return false;
                    }
                    break;

                case "host":
                case "verbose":
                    break;
                    
                default:
                    ParserFailure("Unexpected argument");
                    return false;
            }
        }

        return true;
    }

    static int Main(string[] args)
    {
        var host = "127.0.0.1";

        if (args.Length == 0 || args[0] == "--help")
        {
            ShowUsage();
            return 0;
        }

        for (var i = 0; i < args.Length; i++)
        {
            if (args[i] == "--verbose=true")
            {
                _verbose = true;
                break;
            }
        }

        for (var i = 0; i < args.Length; i++)
        {
            if (args[i].StartsWith("--host="))
            {
                var parts = args[i].Split('=');
                if (parts.Length == 2)
                {
                    host = parts[1];
                }
                break;
            }
        }
        
        if (_verbose)
        {
            Console.WriteLine("[Connecting to host = {0}]", host);
        }

        var c = new SDRconnectWebSocketClient(host);

        c.OnConnected += () =>
        {
            if (_verbose)
            {
                Console.WriteLine("[Connected]");
            }
        };

        c.OnDisconnected += () =>
        {
            if (_verbose)
            {
                Console.WriteLine("[Disconnected]");
            }
        };

        try
        {
            c.Start();
        }
        catch (Exception e)
        {
            Console.WriteLine("[Failed to connect]");
            return 1;
        }

        var result = ParseArguments(args, c);

        c.Stop();

        return result ? 0 : 1;
    }
}