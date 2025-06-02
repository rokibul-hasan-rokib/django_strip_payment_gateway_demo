from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
import stripe
from .models import Product, Order, OrderItem, Payment

def create_checkout_session(request):
    if request.method == 'POST':
        # Get products from cart/session
        product_ids = request.POST.getlist('products')
        quantities = request.POST.getlist('quantities')
        
        # Create order
        order = Order.objects.create(user=request.user)
        
        line_items = []
        for product_id, quantity in zip(product_ids, quantities):
            product = Product.objects.get(id=product_id)
            OrderItem.objects.create(
                order=order,
                product=product,
                price=product.price,
                quantity=quantity
            )
            
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': product.name,
                    },
                    'unit_amount': int(product.price * 100),
                },
                'quantity': int(quantity),
            })
        
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=request.build_absolute_uri(
                    f'/payment/success?session_id={{CHECKOUT_SESSION_ID}}'
                ),
                cancel_url=request.build_absolute_uri('/payment/cancel'),
                metadata={
                    'order_id': order.id
                }
            )
            
            return redirect(checkout_session.url)
        except Exception as e:
            return JsonResponse({'error': str(e)})
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

def payment_success(request):
    session_id = request.GET.get('session_id')
    if session_id:
        session = stripe.checkout.Session.retrieve(session_id)
        
        # Update order status
        order = Order.objects.get(id=session.metadata.order_id)
        order.paid = True
        order.save()
        
        # Create payment record
        Payment.objects.create(
            order=order,
            stripe_id=session.payment_intent,
            amount=order.get_total_cost()
        )
        
        return render(request, 'payment/success.html', {'order': order})
    
    return redirect('home')

def payment_cancel(request):
    return render(request, 'payment/cancel.html')

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return HttpResponse(status=400)

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # Fulfill the purchase
        order = Order.objects.get(id=session.metadata.order_id)
        order.paid = True
        order.save()
        
        Payment.objects.create(
            order=order,
            stripe_id=session.payment_intent,
            amount=order.get_total_cost()
        )

    return HttpResponse(status=200)