using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace SDRconnectWebSocketAPI.Client
{
    public enum SDRconnectProperty
    {
        device_center_frequency = 1,
        device_sample_rate = 2, 
        device_vfo_frequency = 3,
        filter_bandwidth = 4,
        demodulator = 5,
        demod_max_bandwidth = 6, /* read-only */
        started = 7, /* read-only */
        can_control = 8, /* read-only */
        audio_volume_percent = 9,
        audio_mute = 10,
        audio_limiters = 11,
        audio_filter = 12,
        squelch_enable = 13,
        squelch_threshold = 14,
        agc_enable = 15,
        agc_threshold = 16,
        wfm_stereo_enable = 17,
        noise_reduction_enable = 18,
        noise_reduction_strength = 19,
        nfm_deemphasis_enable = 20,
        spectrum_ref_level = 21,
        spectrum_base = 22,
        rds_ps = 23, /* read-only */
        rds_pi = 24, /* read-only */
        rds_enable = 25,
        signal_power = 26, /* read-only */
        signal_snr = 27, /* read-only */
        wfm_stereo = 28, /* read-only */
        am_lowcut_frequency = 29,
        ssb_lowcut_frequency = 30,
        nfm_lowcut_frequency = 31,
        overload = 32, /* read-only */
        lna_state_min = 33, /* read-only */
        lna_state_max = 34, /* read-only */
        lna_state = 35 
    };
}
