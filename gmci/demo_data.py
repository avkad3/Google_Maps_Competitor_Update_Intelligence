"""Demo dataset content (synthetic, clearly labelled as demo data in the UI).

Business names are fictional. Each template is (headline, cta, month_hint, text). ``{biz}`` and
``{area}`` are filled per competitor so competitors publish on the same themes in their own words,
which is how real local markets look.

``FRESH`` templates are held back: the demo scrape source releases them one or two at a time so a
re-scrape shows new posts being added while everything already stored is skipped as a duplicate.
"""

SALON_POSTS = [
    ("Monsoon frizz control", "Learn more", 7, "Monsoon frizz is real! 🌧️ Our stylists at {biz} recommend a sulphate-free shampoo, a leave-in serum and never tying wet hair. Walk in for a 20-minute anti-frizz ritual and leave {area} humidity-proof."),
    ("5 tips to stop hair fall", "Learn more", 0, "Hair fall worrying you? 5 tips from our experts at {biz}: 1) oil 2x a week, not daily 2) use a wide-tooth comb 3) eat enough protein 4) avoid very hot water 5) get a scalp analysis. Book a free scalp check this week in {area}."),
    ("Split ends? Time for a trim", "Book", 0, "Split ends travel up the hair shaft if you ignore them. A dusting trim every 8-10 weeks keeps length healthy. Our {area} team will show you how little needs to go. Book your trim at {biz}."),
    ("Hair oiling: myth vs fact", "Learn more", 0, "Myth: leaving oil overnight makes hair stronger. Fact: 1-2 hours is enough and overnight oil can clog the scalp. Ask our trichology-trained stylists at {biz}, {area} about the right routine for your hair type."),
    ("Diwali glow packages", "Get offer", 10, "This Diwali, glow brighter ✨ {biz} festive package: hair spa + gold facial + manicure at flat 30% off. Valid till 15 Nov at our {area} salon. Call or book online to reserve your slot before the festive rush!"),
    ("Navratri ready looks", "Book", 9, "Garba nights call for hair that stays! 💃 {biz} Navratri special: braided updo + makeup at ₹1,499. Book a slot between 4-8 pm, all nine nights, at our {area} studio."),
    ("Ganesh Chaturthi offer", "Get offer", 9, "Ganpati Bappa Morya! 🙏 Celebrate with 20% off on all facials and hair colour services at {biz}, {area}, this Ganesh Chaturthi week. Offer valid on prepaid bookings."),
    ("Christmas & New Year party looks", "Book", 12, "Party season is here 🎄 Get a blow-dry + party makeup combo for ₹1,999 at {biz}. Free nail art with every New Year's Eve booking in {area}."),
    ("Valentine's couple spa", "Book", 2, "Love is in the hair ❤️ Couple hair spa + head massage at {biz}, {area} for just ₹2,499 this Valentine's week. Limited slots, book now."),
    ("Balayage transformation", "Book", 0, "Before ➡️ After: dull box dye to soft caramel balayage in one sitting. Swipe to see the transformation by our senior colourist at {biz}, {area}. Consultation is free!"),
    ("From frizzy to sleek", "Book", 0, "Before/after of the week: 8 months of frizz to glass-smooth hair with our keratin treatment at {biz}. Results last 4-5 months with the right aftercare. Book your consult in {area}."),
    ("Bob cut makeover", "Book", 0, "Our client wanted a fresh start, so we went from waist-length to a chic French bob! ✂️ Transformation by the {biz} team in {area}. Ready for your big chop?"),
    ("Bridal trial now open", "Book", 11, "Wedding season bookings are open at {biz}! 👰 Book your bridal makeup trial in {area} and get the pre-bridal skin package at 15% off. Airbrush and HD options available."),
    ("Pre-bridal packages", "Book", 0, "Brides-to-be, start your glow journey 3 months before the big day. {biz} pre-bridal package: 6 facials, hair spa, body polishing and manicure-pedicure. Free consultation at our {area} salon."),
    ("Sangeet & mehendi looks", "Book", 11, "Sangeet, mehendi, haldi: one look for every function! Book the {biz} wedding-week package for the bride and family in {area}. Group discounts for 5+ bookings."),
    ("Global hair colour trends", "Book", 0, "Trending this season: chocolate mocha, copper red and soft babylights 🎨 Our colour bar at {biz}, {area} uses ammonia-free colour. Book a strand test and consultation today."),
    ("Grey coverage that lasts", "Book", 0, "Grey roots showing too soon? Our ammonia-free root touch-up lasts 4-6 weeks and is gentle on the scalp. Root touch-up at ₹899 every weekday at {biz}, {area}."),
    ("Keratin vs smoothening", "Learn more", 0, "Keratin, smoothening, botox or nanoplastia? Here's the difference: keratin = frizz control with natural movement, smoothening = poker straight, botox = repair + shine. Not sure? Our {area} experts at {biz} will guide you."),
    ("Hair botox launch", "Book", 0, "Introducing Hair Botox at {biz}! 💆 Deep repair for damaged, coloured hair, with no formaldehyde. Launch price ₹3,499 (regular ₹4,999) at our {area} salon this month."),
    ("HydraFacial now available", "Book", 0, "Now available at {biz}, {area}: HydraFacial 💧 cleanse, extract and hydrate in 45 minutes with zero downtime. First session at an introductory price of ₹2,999."),
    ("D-tan for summer", "Book", 4, "Summer tan got you down? ☀️ Our D-tan cleanup removes sun damage and evens skin tone. Pair it with a hydrating facial at {biz}, {area}, for 25% off this month."),
    ("Acne-safe facials", "Learn more", 0, "Acne-prone skin needs a different facial. Our dermatologist-approved clean-up uses salicylic peel and no harsh scrubs. Ask for the clarifying facial at {biz}, {area}."),
    ("Men's grooming menu", "Book", 0, "Gentlemen, your grooming upgrade is here 💈 Fade cuts, beard sculpting, hot towel shave and de-tan at {biz}, {area}. Haircut + beard combo at ₹599 on weekdays."),
    ("Groom packages", "Book", 11, "Grooms deserve the spotlight too! {biz} groom package: facial, haircut, beard styling, manicure and pedicure. Book 2 weeks before the wedding at our {area} salon."),
    ("Gel nail extensions", "Book", 0, "New nail art collection is in 💅 Gel extensions, French tips, chrome and hand-painted designs at {biz}, {area}. Gel polish lasts up to 3 weeks."),
    ("Mani-pedi Monday", "Get offer", 0, "Mani-Pedi Mondays at {biz}! Spa manicure + pedicure at flat ₹999 every Monday in {area}. Walk in or book ahead."),
    ("Meet our senior stylist", "Book", 0, "Meet our senior stylist at {biz}, 12 years of experience with precision cuts and curly hair. Certified by L'Oréal Professionnel. Book a session with our {area} expert."),
    ("Our certified colourists", "Learn more", 0, "Our team of certified colourists at {biz} trained in Mumbai and Bangkok. Every colour service starts with a strand test and a shade consultation at our {area} salon."),
    ("Client love", "Learn more", 0, "\"Best haircut I've had in {area}! The stylist actually listened.\" ⭐⭐⭐⭐⭐ Thank you for the lovely review! Happy clients make our day at {biz}."),
    ("5-star wedding review", "Learn more", 0, "Our bride said: \"My makeup stayed perfect from pheras to reception. Thank you, team {biz}!\" Thank you for trusting us with your big day. ❤️"),
    ("Membership launch", "Sign up", 0, "Introducing the {biz} Glow Membership 🌟 Pay ₹5,000, get services worth ₹6,500, plus 10% off every visit for a year. Available at our {area} salon."),
    ("Refer a friend", "Learn more", 0, "Refer a friend to {biz} and you both get ₹300 off your next service! Just share your name at billing. Valid at our {area} branch."),
    ("Hygiene first", "Learn more", 0, "Your safety matters. At {biz}, every tool is sterilised after each use, we use disposable kits for pedicures, and stations are sanitised between clients in {area}."),
    ("New branch opening", "Learn more", 0, "We're growing! 🎉 {biz} opens a new branch near {area} station this month. Opening week: 20% off all services. See you there!"),
    ("Festival holiday timings", "Call now", 10, "Diwali timings at {biz}, {area}: open 9 am-10 pm till Laxmi Pujan, closed on Padwa. Pre-book festive appointments to avoid waiting."),
    ("Summer hair spa", "Book", 5, "Sun, chlorine and sweat dry your hair out ☀️ Our summer hydration hair spa at {biz}, {area} restores moisture in 45 minutes. ₹1,199 this month."),
    ("Curly hair care", "Learn more", 0, "Curly girls, this one's for you 🌀 Our {area} stylists are trained in the curly girl method: dry cuts, no sulphates, defined curls. Book a curl consultation at {biz}."),
    ("Kids haircuts", "Book", 6, "Back-to-school haircuts for kids at {biz}, {area}! ✂️ Quick, gentle cuts with a free hair accessory. Kids' cut at ₹299 every weekend."),
]

SALON_FRESH = [
    ("Scalp detox treatment", "Book", 0, "New: Scalp Detox at {biz} 🌿 Charcoal + exfoliation to remove buildup and calm an itchy scalp. Introductory price ₹1,299 at our {area} salon."),
    ("Weekday happy hours", "Get offer", 0, "Weekday Happy Hours at {biz}: 2-5 pm, get 25% off on haircuts, colour and spa in {area}. Beat the weekend rush!"),
    ("Dussehra makeover offer", "Get offer", 10, "Celebrate Dussehra with a new look ✨ Flat 20% off on hair colour and keratin at {biz}, {area}. Offer valid this week only."),
    ("Heat styling damage tips", "Learn more", 0, "Straighten or curl every day? Always use a heat protectant, keep tools below 180°C and get a deep-conditioning spa monthly. Our {biz} team in {area} can help repair damage."),
    ("Engagement look of the week", "Book", 0, "Engagement look of the week 💍 Soft glam with a messy bun and fresh flowers by the {biz} bridal team in {area}. Book your trial now."),
    ("Olaplex bond repair", "Book", 0, "Bleached hair? Add Olaplex bond repair to any colour service at {biz} to keep hair strong. Now available at our {area} studio."),
]

DENTAL_POSTS = [
    ("Brushing mistakes", "Learn more", 0, "Are you brushing too hard? Brushing aggressively wears enamel and causes gum recession. Use a soft brush, 2 minutes, twice a day. Questions? Visit {biz}, {area}."),
    ("Flossing 101", "Learn more", 0, "Flossing reaches the 40% of tooth surfaces your brush can't. Our hygienists at {biz} will show you the right technique at your next check-up in {area}."),
    ("Bleeding gums?", "Book", 0, "Bleeding gums are not normal. They are often the first sign of gingivitis, which is reversible if treated early. Book a gum check-up at {biz}, {area}."),
    ("Teeth whitening offer", "Get offer", 0, "Brighter smile in 60 minutes 😁 In-clinic laser teeth whitening at {biz}, {area}: flat 25% off this month. Free shade check with every consultation."),
    ("Festive smile offer", "Get offer", 10, "Smile brighter this Diwali 🪔 Teeth whitening + cleaning combo at ₹4,999 at {biz}, {area}. Offer valid till 10 Nov."),
    ("Invisible aligners", "Book", 0, "Straighten your teeth without metal braces! Clear aligners are removable, nearly invisible and comfortable. Free 3D smile scan at {biz}, {area} this month."),
    ("Braces for teens", "Learn more", 0, "Is your child's bite crooked? The best time for an orthodontic check is age 7-12. Metal, ceramic and clear braces options at {biz}, {area}."),
    ("Dental implants explained", "Learn more", 0, "Missing teeth? A dental implant is a titanium root that holds a natural-looking crown and lasts decades. Implant consultation with a 3D scan at {biz}, {area}."),
    ("Implant EMI", "Get offer", 0, "Dental implants are now affordable with 0% EMI options at {biz}. Book a free implant consultation at our {area} clinic."),
    ("Kids' first dental visit", "Book", 6, "Your child's first dental visit should be by their first birthday 🦷 Our child-friendly team at {biz}, {area} makes it fun, with stickers included!"),
    ("Painless root canal", "Learn more", 0, "Root canal myths: it is NOT painful anymore. With modern rotary tools and good anaesthesia, single-sitting RCT at {biz}, {area} feels like a filling."),
    ("Free dental check-up camp", "Sign up", 0, "Free dental check-up camp this Sunday at {biz}, {area}! 🦷 Oral screening, cleaning advice and consultation, 10 am-2 pm. Register to reserve a slot."),
    ("Patient review", "Learn more", 0, "\"Got my root canal done without any pain. Very gentle doctor and clean clinic.\" ⭐⭐⭐⭐⭐ Thank you for the kind words! - Team {biz}"),
    ("Smile makeover story", "Book", 0, "Smile makeover before/after: chipped and stained front teeth to a natural, even smile with 6 veneers. Completed in 2 visits at {biz}, {area}."),
    ("Sterilisation protocol", "Learn more", 0, "Your safety first: {biz} follows a strict sterilisation protocol, with autoclaved instruments, disposable needles and sealed kits for every patient in {area}."),
    ("Meet our orthodontist", "Book", 0, "Meet our orthodontist at {biz}: MDS, 10+ years and 500+ aligner cases. Book a consultation at our {area} clinic."),
    ("Sensitivity tips", "Learn more", 0, "Teeth sensitive to cold? Use a desensitising toothpaste, avoid whitening toothpastes for a while, and get checked for enamel wear. Visit {biz}, {area}."),
    ("Sunday timings", "Call now", 0, "Good news! {biz}, {area} is now open on Sundays, 10 am-2 pm, for check-ups and emergencies. Call to book."),
]

DENTAL_FRESH = [
    ("Mouthguards for athletes", "Learn more", 0, "Play contact sports? A custom mouthguard protects teeth and jaw far better than store-bought ones. Get fitted at {biz}, {area}."),
    ("World Oral Health Day", "Sign up", 3, "World Oral Health Day special: free fluoride application for kids under 12 at {biz}, {area} this week."),
    ("Wisdom tooth pain", "Book", 0, "Wisdom tooth pain? An X-ray shows if it is impacted. Same-day consultation and painless extraction at {biz}, {area}."),
]

PROJECTS = [
    {
        "name": "ABC Salon",
        "industry": "Hair & beauty salon",
        "location": "Kharghar, Navi Mumbai",
        "own": ("ABC Salon, Kharghar", "Sector 12, Kharghar, Navi Mumbai"),
        "own_templates": [1, 9, 22, 28],   # indices into SALON_POSTS: a narrow mix, so gaps show up
        "keywords": ["salon in Kharghar", "salon in Bandra", "salon in Khar"],
        "posts": SALON_POSTS, "fresh": SALON_FRESH,
        "competitors": [
            ("Glamour Studio Unisex Salon", "Sector 20, Kharghar, Navi Mumbai", "Kharghar", "Hair salon"),
            ("Mirror Mirror Hair & Beauty", "Sector 17, Vashi, Navi Mumbai", "Vashi", "Beauty salon"),
            ("The Style Lounge", "Hill Road, Bandra West, Mumbai", "Bandra", "Hair salon"),
            ("Velvet Touch Salon", "Linking Road, Khar West, Mumbai", "Khar", "Beauty salon"),
            ("Urban Mane Studio", "CBD Belapur, Navi Mumbai", "Belapur", "Hair salon"),
            ("Blush & Brush Makeover Studio", "Sector 35, Kharghar, Navi Mumbai", "Kharghar", "Makeup artist"),
            ("Scissors & Co.", "Sector 19, Nerul, Navi Mumbai", "Nerul", "Hair salon"),
            ("Tress Tales Hair Studio", "Pali Hill, Bandra West, Mumbai", "Bandra", "Hair salon"),
        ],
        "discoverable": [
            ("Glamour Studio Unisex Salon", "Sector 20, Kharghar, Navi Mumbai", "Hair salon", 4.6, "salon in Kharghar"),
            ("Blush & Brush Makeover Studio", "Sector 35, Kharghar, Navi Mumbai", "Makeup artist", 4.8, "salon in Kharghar"),
            ("Shear Bliss Family Salon", "Sector 7, Kharghar, Navi Mumbai", "Hair salon", 4.3, "salon in Kharghar"),
            ("Lotus Beauty Parlour", "Sector 10, Kharghar, Navi Mumbai", "Beauty parlour", 4.1, "salon in Kharghar"),
            ("The Style Lounge", "Hill Road, Bandra West, Mumbai", "Hair salon", 4.5, "salon in Bandra"),
            ("Tress Tales Hair Studio", "Pali Hill, Bandra West, Mumbai", "Hair salon", 4.7, "salon in Bandra"),
            ("Bandstand Barbers", "Bandstand, Bandra West, Mumbai", "Barber shop", 4.4, "salon in Bandra"),
            ("Velvet Touch Salon", "Linking Road, Khar West, Mumbai", "Beauty salon", 4.2, "salon in Khar"),
            ("Khar Hair Lab", "14th Road, Khar West, Mumbai", "Hair salon", 4.6, "salon in Khar"),
        ],
    },
    {
        "name": "SmileCare Dental",
        "industry": "Dental clinic",
        "location": "Baner, Pune",
        "own": ("SmileCare Dental Clinic, Baner", "Baner Road, Pune"),
        "own_templates": [0, 12],
        "keywords": ["dentist in Baner", "dental clinic in Aundh", "teeth whitening Pune"],
        "posts": DENTAL_POSTS, "fresh": DENTAL_FRESH,
        "competitors": [
            ("Pearl Dental Studio", "Baner, Pune", "Baner", "Dental clinic"),
            ("BrightBite Dental Care", "Aundh, Pune", "Aundh", "Dentist"),
            ("Tooth Tales Family Dentistry", "Balewadi, Pune", "Balewadi", "Dental clinic"),
            ("Align32 Orthodontics", "Pashan, Pune", "Pashan", "Orthodontist"),
            ("Dentique Multispeciality Clinic", "Wakad, Pune", "Wakad", "Dental clinic"),
        ],
        "discoverable": [
            ("Pearl Dental Studio", "Baner, Pune", "Dental clinic", 4.7, "dentist in Baner"),
            ("Baner Smile Centre", "Baner-Pashan Link Road, Pune", "Dentist", 4.5, "dentist in Baner"),
            ("BrightBite Dental Care", "Aundh, Pune", "Dentist", 4.6, "dental clinic in Aundh"),
            ("Aundh Dental Hub", "ITI Road, Aundh, Pune", "Dental clinic", 4.2, "dental clinic in Aundh"),
        ],
    },
]
