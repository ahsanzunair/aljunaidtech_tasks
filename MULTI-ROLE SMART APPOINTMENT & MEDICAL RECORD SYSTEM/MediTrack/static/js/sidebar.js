document.addEventListener("DOMContentLoaded", function () {
    const sidebar = document.getElementById("sidebar");
    const mainContent = document.getElementById("main-content");
    const footer = document.getElementById("main-footer");
    const desktopToggle = document.getElementById("sidebarToggle");
    const mobileToggle = document.getElementById("mobileSidebarToggle");

    // Desktop toggle functionality
    if (desktopToggle) {
        desktopToggle.addEventListener("click", function () {
            sidebar.classList.toggle("collapsed");
            mainContent.classList.toggle("collapsed");
            footer.classList.toggle("collapsed");
        });
    }

    // Mobile toggle functionality
    if (mobileToggle) {
        mobileToggle.addEventListener("click", function () {
            sidebar.classList.toggle("active");
        });
    }

    // Close sidebar when clicking outside on mobile
    document.addEventListener("click", function (event) {
        if (window.innerWidth <= 992) {
            const isClickInsideSidebar = sidebar.contains(event.target);
            const isClickOnMobileToggle = mobileToggle.contains(event.target);
            
            if (!isClickInsideSidebar && !isClickOnMobileToggle) {
                sidebar.classList.remove("active");
            }
        }
    });
});