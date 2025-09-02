// Updated WhiBO Client-Side Script
document.addEventListener('DOMContentLoaded', function() {
    // Auto-hide alerts
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.style.opacity = '0';
            setTimeout(() => alert.remove(), 300);
        }, 5000);
    });

    // URL Validation
    const urlInput = document.getElementById('url');
    if (urlInput) {
        urlInput.addEventListener('input', function() {
            const url = this.value;
            const isValid = validateYouTubeURL(url);
            
            if (url && !isValid) {
                this.classList.add('is-invalid');
            } else {
                this.classList.remove('is-invalid');
            }
        });
    }

    // Download notification system
    window.showNotification = function(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} position-fixed top-0 end-0 m-3`;
        notification.style.zIndex = '9999';
        notification.style.minWidth = '300px';
        notification.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : 'info-circle'}"></i> 
            ${message}
            <button type="button" class="btn-close" onclick="this.parentElement.remove()"></button>
        `;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    };

    // Client info display
    const clientIP = document.body.getAttribute('data-client-ip');
    if (clientIP) {
        console.log('WhiBO Client IP:', clientIP);
    }
});

function validateYouTubeURL(url) {
    const regex = /^(https?\:\/\/)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)\/(watch\?v=|embed\/|v\/|.+\?v=)?([^&=%\?]{11})/;
    return regex.test(url);
}

// Enhanced progress tracking with client feedback
function updateProgressWithClientInfo(percentage, text, downloadId) {
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');
    const progressPercentage = document.getElementById('progress-percentage');
    
    if (progressBar) progressBar.style.width = percentage + '%';
    if (progressPercentage) progressPercentage.textContent = percentage + '%';
    if (progressText) {
        progressText.innerHTML = `
            <i class="fas fa-download"></i> ${text}
            <small class="d-block text-muted">Download ID: ${downloadId.slice(-8)}</small>
        `;
    }
}

// Download completion handler
function handleDownloadComplete(downloadId, filename) {
    showNotification(`✅ ${filename} ready for download!`, 'success');
    
    // Auto-start download after 2 seconds
    setTimeout(() => {
        const downloadLink = document.getElementById('download-file-btn');
        if (downloadLink) {
            downloadLink.click();
            showNotification('📥 Download started to your device', 'info');
        }
    }, 2000);
}

// Network error handler
function handleNetworkError(error) {
    showNotification(`❌ Network error: ${error}`, 'danger');
    console.error('WhiBO Network Error:', error);
}

// File size formatter
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Client-specific download tracking
let clientDownloads = JSON.parse(localStorage.getItem('whibo_downloads') || '[]');

function trackClientDownload(filename, downloadId, quality) {
    const download = {
        filename: filename,
        downloadId: downloadId,
        quality: quality,
        timestamp: new Date().toISOString(),
        status: 'completed'
    };
    
    clientDownloads.unshift(download);
    if (clientDownloads.length > 50) {
        clientDownloads = clientDownloads.slice(0, 50); // Keep only last 50
    }
    
    localStorage.setItem('whibo_downloads', JSON.stringify(clientDownloads));
}

// Display client download history
function showClientHistory() {
    const downloads = JSON.parse(localStorage.getItem('whibo_downloads') || '[]');
    console.log('Your WhiBO Download History:', downloads);
    return downloads;
}
