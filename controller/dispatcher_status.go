package controller

import (
	"net/http"
	"strings"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/gin-gonic/gin"
)

// GetDispatcherStatus proxies the private dispatcher status endpoint so the
// admin UI does not need direct access to the 961 host.
func GetDispatcherStatus(c *gin.Context) {
	statusURL := strings.TrimRight(common.GetEnvOrDefaultString("DISPATCHER_STATUS_URL", "http://192.168.9.61:4010/status"), "/")
	request, err := http.NewRequestWithContext(c.Request.Context(), http.MethodGet, statusURL, nil)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"success": false, "message": "invalid dispatcher status URL"})
		return
	}

	client := &http.Client{Timeout: 5 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		c.JSON(http.StatusBadGateway, gin.H{"success": false, "message": "dispatcher status unavailable"})
		return
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		c.JSON(http.StatusBadGateway, gin.H{"success": false, "message": "dispatcher status returned an error"})
		return
	}

	c.Header("Cache-Control", "no-store")
	c.DataFromReader(http.StatusOK, response.ContentLength, response.Header.Get("Content-Type"), response.Body, nil)
}
