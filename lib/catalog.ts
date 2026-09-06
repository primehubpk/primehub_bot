export type Product={id:string;name:string;category:"bangles"|"watches";image:string;retailPrice:number;wholesalePrice:number;sizes:string[]};

export const MOCK_CATALOG:Product[]=[
{id:"BNG-101",name:"Kashmiri Gold Bangles",category:"bangles",image:"https://images.unsplash.com/photo-1617038260897-41a1f14a8ca0?auto=format&fit=crop&w=800&q=80",retailPrice:1499,wholesalePrice:1199,sizes:["2.4","2.6","2.8"]},
{id:"BNG-102",name:"Pearl Bridal Bangles",category:"bangles",image:"https://images.unsplash.com/photo-1605100804763-247f67b3557e?auto=format&fit=crop&w=800&q=80",retailPrice:1899,wholesalePrice:1499,sizes:["2.4","2.6","2.8"]},
{id:"BNG-103",name:"Marble Kara Set",category:"bangles",image:"https://images.unsplash.com/photo-1573408301185-9146fe634ad0?auto=format&fit=crop&w=800&q=80",retailPrice:999,wholesalePrice:799,sizes:["2.4","2.6"]},
{id:"BNG-104",name:"Mehroon Fancy Bangles",category:"bangles",image:"https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",retailPrice:1299,wholesalePrice:999,sizes:["2.6","2.8"]},
{id:"BNG-105",name:"Silver Stone Kara",category:"bangles",image:"https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",retailPrice:1599,wholesalePrice:1249,sizes:["2.4","2.6","2.8"]},
{id:"BNG-106",name:"Multi Color Party Bangles",category:"bangles",image:"https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=800&q=80",retailPrice:1199,wholesalePrice:899,sizes:["2.4","2.6","2.8"]},
{id:"WAT-201",name:"Classic Black Watch",category:"watches",image:"https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=800&q=80",retailPrice:2499,wholesalePrice:1999,sizes:["Adjustable"]},
{id:"WAT-202",name:"Rose Gold Ladies Watch",category:"watches",image:"https://images.unsplash.com/photo-1524805444758-089113d48a6d?auto=format&fit=crop&w=800&q=80",retailPrice:2799,wholesalePrice:2199,sizes:["Adjustable"]},
{id:"WAT-203",name:"Steel Blue Dial Watch",category:"watches",image:"https://images.unsplash.com/photo-1523170335258-f5ed11844a49?auto=format&fit=crop&w=800&q=80",retailPrice:3199,wholesalePrice:2599,sizes:["Adjustable"]}
];

export function searchCatalog(query:string,shown:string[]=[],limit=3){
 const q=query.toLowerCase();
 const category=q.includes("watch")||q.includes("ghari")?"watches":q.includes("bangle")||q.includes("kara")||q.includes("churi")?"bangles":null;
 const candidates=MOCK_CATALOG.filter(p=>(!category||p.category===category)&&!shown.includes(p.id));
 return candidates.slice(0,Math.max(1,Math.min(limit,3)));
}
export function getProduct(id:string){return MOCK_CATALOG.find(p=>p.id===id)||null;}
