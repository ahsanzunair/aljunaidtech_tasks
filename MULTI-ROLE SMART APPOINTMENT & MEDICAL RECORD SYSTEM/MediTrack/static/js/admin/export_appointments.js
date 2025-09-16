$(document).ready(function() {
    // Initialize tooltips
    $('[data-bs-toggle="tooltip"]').tooltip();

    // Cancel appointment modal setup
    $('#cancelModal').on('show.bs.modal', function(event) {
        const button = $(event.relatedTarget);
        const appointmentId = button.data('appointment-id');
        const appointmentInfo = button.data('appointment-info');
        
        const modal = $(this);
        modal.find('#cancelAppointmentText').html(
            `Are you sure you want to cancel the appointment:<br><strong>${appointmentInfo}</strong>?`
        );
        modal.find('#cancelAppointmentForm').attr('action', `/appointments/${appointmentId}/cancel/`);
    });

    // Export modal date range toggle
    $('#exportDateRange').change(function() {
        if ($(this).val() === 'custom') {
            $('#customDateRange').show();
        } else {
            $('#customDateRange').hide();
        }
    });

    // Auto-submit filters when dropdowns change
    $('#statusFilter, #doctorFilter').change(function() {
        $(this).closest('form').submit();
    });
});