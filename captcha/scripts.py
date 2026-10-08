"""Script JavaScript inject vào elevenlabs.io để kích hoạt invisible hCaptcha widget."""

from config.constants import HCAPTCHA_SITEKEY

HCAPTCHA_TRIGGER_JS = f"""
() => {{
    return new Promise((resolve, reject) => {{
        try {{
            // Xóa React App DOM để giảm tải CPU/RAM nhưng giữ lại các script và iframe cần thiết
            const root = document.getElementById('__next') || document.getElementById('root');
            if (root) root.remove();
            document.querySelectorAll('video, audio').forEach(el => el.remove());
        }} catch(e) {{}}

        function doCaptcha() {{
            const sitekey = '{HCAPTCHA_SITEKEY}';
            const div = document.createElement('div');
            // Container vô hình nhưng có kích thước thực để tránh lỗi challenge-error của hCaptcha
            div.style.position = 'fixed';
            div.style.bottom = '10px';
            div.style.right = '10px';
            div.style.width = '150px';
            div.style.height = '150px';
            div.style.opacity = '0.01';
            div.style.pointerEvents = 'none';
            div.style.zIndex = '999999';
            document.body.appendChild(div);

            try {{
                const widgetId = window.hcaptcha.render(div, {{
                    sitekey: sitekey,
                    size: 'invisible',
                    callback: function(token) {{
                        try {{ div.remove(); }} catch(e) {{}}
                        resolve(token);
                    }},
                    'error-callback': function(err) {{
                        try {{ div.remove(); }} catch(e) {{}}
                        reject('hCaptcha error: ' + JSON.stringify(err));
                    }},
                    'close-callback': function() {{
                        try {{ div.remove(); }} catch(e) {{}}
                        reject('hCaptcha closed');
                    }}
                }});

                window.hcaptcha.reset(widgetId);
                window.hcaptcha.execute(widgetId);
            }} catch (err) {{
                try {{ div.remove(); }} catch(e) {{}}
                reject('Execute exception: ' + String(err));
            }}
        }}

        if (!window.hcaptcha) {{
            const script = document.createElement('script');
            script.src = 'https://js.hcaptcha.com/1/api.js';
            document.head.appendChild(script);

            let checkCount = 0;
            const timer = setInterval(() => {{
                if (window.hcaptcha) {{
                    clearInterval(timer);
                    doCaptcha();
                }}
                if (checkCount++ > 60) {{
                    clearInterval(timer);
                    reject('Timeout loading hCaptcha api.js');
                }}
            }}, 250);
        }} else {{
            doCaptcha();
        }}
    }});
}}
"""
