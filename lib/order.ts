export type OrderCartItem={productId:string;qty:number;name:string;image:string;price:number;size?:string;color?:string};
export type CustomerDetails={fullName:string;phone:string;city:string;address:string;notes?:string};

export function cartTotal(cart:OrderCartItem[]){return cart.reduce((sum,item)=>sum+(Number(item.price)||0)*(Number(item.qty)||0),0);}
export function remainingAfterAdvance(total:number,advance=300){return Math.max(0,total-advance);}
export function cleanPhone(value:string){return value.replace(/[^0-9+]/g,"").slice(0,20);}
export function validCustomer(details:CustomerDetails){return Boolean(details.fullName.trim()&&cleanPhone(details.phone).length>=10&&details.city.trim()&&details.address.trim());}
export function whatsappOrderText(orderId:string,details:CustomerDetails,cart:OrderCartItem[],total:number){
 const items=cart.map((item,index)=>`${index+1}. ${item.name} x${item.qty} · ${item.size||"N/A"} · ${item.color||"As shown"}`).join("\n");
 return `Assalam-o-Alaikum PrimeHubMaal\nNew order: ${orderId}\nName: ${details.fullName}\nCity: ${details.city}\nItems:\n${items}\nTotal: Rs ${total}\nRs 300 advance pending.`;
}
export function whatsappOrderUrl(orderId:string,details:CustomerDetails,cart:OrderCartItem[],total:number){return `https://wa.me/923238878009?text=${encodeURIComponent(whatsappOrderText(orderId,details,cart,total))}`;}
