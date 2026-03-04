using System;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SDRconnectWebSocketAPI.Client
{

    #region Internal
    internal class SDRconnectWebSocketMessageInternal
    {
        #region Static Functions
        public static SDRconnectWebSocketMessageInternal? FromJson(string json)
        {
            return JsonSerializer.Deserialize(json, typeof(SDRconnectWebSocketMessageInternal), SDRconnectWebSocketMessageInternalSourceGenerationContext.Default) as SDRconnectWebSocketMessageInternal;
        }

        public static string ToJson(SDRconnectWebSocketMessageInternal o)
        {
            return JsonSerializer.Serialize(o, typeof(SDRconnectWebSocketMessageInternal), SDRconnectWebSocketMessageInternalSourceGenerationContext.Default);
        }

        #endregion

        public string? event_type { get; set; }

        public string? property { get; set; }
        public string? value { get; set; }
    }

    [JsonSourceGenerationOptions(WriteIndented = true)]
    [JsonSerializable(typeof(SDRconnectWebSocketMessageInternal))]
    internal partial class SDRconnectWebSocketMessageInternalSourceGenerationContext : JsonSerializerContext
    {
    }
    #endregion

    public class SDRconnectWebSocketMessage
    {
        public enum MessageType
        {
            None = 0,
            PropertyChanged = 1,

            SetPropertyRequest = 2,

            GetPropertyRequest = 3,
            GetPropertyResponse = 4,

            AudioStreamEnable = 5,
            IqStreamEnable = 6,
            SpectrumEnable = 7,
            DeviceStreamEnable = 8,
            SelectedDeviceIndex = 9,
            StartRecording = 10,
            StopRecording = 11,
            ApplyDeviceProfile = 12,
            SelectedDeviceSerial = 13,
            SelectedDeviceName = 14
        };

        public MessageType Type { get; set; }
        public string? Property { get; set; }
        public string? Value { get; set; }


        #region Static Functions
        public static SDRconnectWebSocketMessage FromJson(string jsonText, out bool valid)
        {
            var message = new SDRconnectWebSocketMessage();
            try
            {
                var o = SDRconnectWebSocketMessageInternal.FromJson(jsonText);

                switch (o.event_type)
                {
                    case "property_changed":
                        message.Type = MessageType.PropertyChanged;
                        valid = true;
                        break;

                    case "set_property":
                        message.Type = MessageType.SetPropertyRequest;
                        valid = true;
                        break;

                    case "get_property":
                        message.Type = MessageType.GetPropertyRequest;
                        valid = true;
                        break;

                    case "get_property_response":
                        message.Type = MessageType.GetPropertyResponse;
                        valid = true;
                        break;

                    case "audio_stream_enable":
                        message.Type = MessageType.AudioStreamEnable;
                        valid = true;
                        break;

                    case "iq_stream_enable":
                        message.Type = MessageType.IqStreamEnable;
                        valid = true;
                        break;

                    case "spectrum_enable":
                        message.Type = MessageType.SpectrumEnable;
                        valid = true;
                        break;

                    case "device_stream_enable":
                        message.Type = MessageType.DeviceStreamEnable;
                        valid = true;
                        break;

                    case "selected_device":
                        message.Type = MessageType.SelectedDeviceIndex;
                        valid = true;
                        break;

                    case "selected_device_serial":
                        message.Type = MessageType.SelectedDeviceSerial;
                        valid = true; 
                        break;

                    case "selected_device_name":
                        message.Type = MessageType.SelectedDeviceName;
                        valid = true;
                        break;

                    case "start_recording":
                        message.Type = MessageType.StartRecording;
                        valid = true;
                        break;

                    case "stop_recording":
                        message.Type = MessageType.StopRecording;
                        valid = true;
                        break;

                    case "apply_device_profile":
                        message.Type = MessageType.ApplyDeviceProfile;
                        valid = true;
                        break;

                    default:
                        valid = false;
                        break;
                }

                message.Property = o.property;
                message.Value = o.value;

                return message;
            }
            catch
            {
                valid = false;
                return message;
            }
        }

        public static string ToJson(SDRconnectWebSocketMessage o)
        {
            var message = new SDRconnectWebSocketMessageInternal();

            switch (o.Type)
            {
                case MessageType.PropertyChanged:
                    message.event_type = "property_changed";
                    break;

                case MessageType.SetPropertyRequest:
                    message.event_type = "set_property";
                    break;

                case MessageType.GetPropertyRequest:
                    message.event_type = "get_property";
                    break;

                case MessageType.GetPropertyResponse:
                    message.event_type = "get_property_response";
                    break;

                case MessageType.AudioStreamEnable:
                     message.event_type = "audio_stream_enable";
                    break;

                case MessageType.IqStreamEnable:
                    message.event_type = "iq_stream_enable";
                    break;

                case MessageType.SpectrumEnable:
                    message.event_type = "spectrum_enable";
                    break;

                case MessageType.DeviceStreamEnable:
                    message.event_type = "device_stream_enable";
                    break;

                case MessageType.SelectedDeviceIndex:
                    message.event_type = "selected_device";
                    break;

                case MessageType.SelectedDeviceSerial:
                    message.event_type = "selected_device_serial";
                    break;

                case MessageType.SelectedDeviceName:
                    message.event_type = "selected_device_name";
                    break;

                case MessageType.StartRecording:
                    message.event_type = "start_recording";
                    break;

                case MessageType.StopRecording:
                    message.event_type = "stop_recording";
                    break;

                case MessageType.ApplyDeviceProfile:
                    message.event_type = "apply_device_profile";
                    break;

            }

            message.property = o.Property;
            message.value = o.Value;

            return SDRconnectWebSocketMessageInternal.ToJson(message);
        }

        #endregion
    }
}
