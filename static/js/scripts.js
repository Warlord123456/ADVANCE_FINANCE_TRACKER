document.addEventListener('DOMContentLoaded', () => {
    // DARK MODE TOGGLE
    const darkModeToggle = document.getElementById('darkModeToggle');
    if (darkModeToggle) {
      darkModeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        const darkModeIcon = document.getElementById('darkModeIcon');
        if (document.body.classList.contains('dark-mode')) {
          darkModeIcon && darkModeIcon.classList.replace('fa-moon', 'fa-sun');
        } else {
          darkModeIcon && darkModeIcon.classList.replace('fa-sun', 'fa-moon');
        }
      });
    }
  
    // REGISTER SERVICE WORKER FOR PWA OFFLINE SUPPORT
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/js/service-worker.js')
        .then(registration => {
          console.log('Service Worker registered with scope:', registration.scope);
        })
        .catch(error => {
          console.error('Service Worker registration failed:', error);
        });
    }
  
    // REAL-TIME OCR PREVIEW
    const receiptInput = document.getElementById('receipt_files');
    if (receiptInput) {
      receiptInput.addEventListener('change', () => {
        // If multiple files are selected, process only the first one for preview.
        const file = receiptInput.files[0];
        if (file) {
          const formData = new FormData();
          formData.append('file', file);
          fetch('/ocr_preview', {
            method: 'POST',
            body: formData
          })
          .then(response => {
            if (!response.ok) {
              throw new Error('Network response was not ok');
            }
            return response.json();
          })
          .then(data => {
            console.log("OCR Preview:", data.ocr_text);
            // Optionally, update a preview element in your UI:
            // document.getElementById('ocrPreview').textContent = data.ocr_text;
          })
          .catch(error => {
            console.error('Error fetching OCR preview:', error);
          });
        }
      });
    }
  
    // VOICE COMMAND SUPPORT (STUB)
    // If you have a button to start voice commands, e.g., with id "startVoiceCommand"
    const voiceButton = document.getElementById('startVoiceCommand');
    if (voiceButton && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognition = new SpeechRecognition();
      recognition.lang = 'en-US';
      recognition.continuous = false;
      recognition.interimResults = false;
      
      voiceButton.addEventListener('click', () => {
        recognition.start();
      });
      
      recognition.addEventListener('result', event => {
        const transcript = Array.from(event.results)
          .map(result => result[0])
          .map(result => result.transcript)
          .join('');
        console.log('Voice Command:', transcript);
        // Process the transcript as needed (e.g., trigger a search or navigation)
      });
      
      recognition.addEventListener('error', event => {
        console.error('Speech recognition error:', event.error);
      });
    }
  });
  